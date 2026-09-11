from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.domain.rag import ChatMessage, GeneratedText, Usage


class ModelConfigurationError(RuntimeError):
    """Raised locally before a model call when required configuration is absent."""


class ModelUpstreamError(RuntimeError):
    """Sanitized failure raised for a DeepSeek transport or protocol error."""


class DeepSeekChatClient:
    """Small, explicit adapter for DeepSeek's OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-v4-flash",
        timeout_seconds: float = 60.0,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        thinking_enabled: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_enabled = thinking_enabled
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def generate(self, messages: Sequence[ChatMessage]) -> GeneratedText:
        if not self._api_key:
            raise ModelConfigurationError(
                "DEEPSEEK_API_KEY is required before DeepSeek can be called."
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.to_payload() for message in messages],
            "stream": False,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        # DeepSeek documents thinking as an opt-in request parameter.
        if self._thinking_enabled:
            payload["thinking"] = {"type": "enabled"}

        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_seconds)
        if self._http_client is None:
            self._http_client = client

        try:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ModelUpstreamError("DeepSeek request failed.") from exc

        if response.is_error:
            raise ModelUpstreamError(
                f"DeepSeek returned HTTP status {response.status_code}."
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUpstreamError("DeepSeek returned an invalid response shape.") from exc

        if not isinstance(content, str) or not content.strip():
            raise ModelUpstreamError("DeepSeek returned an empty response.")

        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=_as_non_negative_int(usage_data.get("prompt_tokens")),
            completion_tokens=_as_non_negative_int(usage_data.get("completion_tokens")),
            total_tokens=_as_non_negative_int(usage_data.get("total_tokens")),
        )
        returned_model = data.get("model")
        return GeneratedText(
            content=content,
            model=returned_model if isinstance(returned_model, str) else self._model,
            usage=usage,
        )

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


def _as_non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
