from __future__ import annotations

import asyncio
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
        model: str = "deepseek-flash",
        timeout_seconds: float = 60.0,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        thinking_enabled: bool = False,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.25,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._thinking_enabled = thinking_enabled
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
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
        # DeepSeek Flash can enable thinking when the parameter is omitted.
        # Always send the explicit mode so a disabled-thinking request cannot
        # spend the output budget on reasoning_content and leave content empty.
        payload["thinking"] = {
            "type": "enabled" if self._thinking_enabled else "disabled"
        }

        client = self._http_client or httpx.AsyncClient(timeout=self._timeout_seconds)
        if self._http_client is None:
            self._http_client = client

        for attempt in range(self._max_retries + 1):
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
                if attempt < self._max_retries:
                    await self._wait_before_retry(attempt)
                    continue
                raise ModelUpstreamError("DeepSeek request failed.") from exc

            if response.is_error:
                if (
                    self._is_retryable_status(response.status_code)
                    and attempt < self._max_retries
                ):
                    await self._wait_before_retry(attempt)
                    continue
                raise ModelUpstreamError(
                    f"DeepSeek returned HTTP status {response.status_code}."
                )
            break
        else:
            raise AssertionError("DeepSeek retry loop must return or raise")

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

    async def _wait_before_retry(self, attempt: int) -> None:
        if self._retry_backoff_seconds <= 0:
            return
        await asyncio.sleep(min(self._retry_backoff_seconds * (2**attempt), 4.0))

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code in {408, 409, 425, 429} or 500 <= status_code <= 599

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


def _as_non_negative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0
