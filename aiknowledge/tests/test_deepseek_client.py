from __future__ import annotations

import json

import httpx
import pytest

from app.domain.rag import ChatMessage
from app.infrastructure.llm.deepseek import (
    DeepSeekChatClient,
    ModelConfigurationError,
    ModelUpstreamError,
)


@pytest.mark.asyncio
async def test_deepseek_client_uses_the_current_flash_model_and_openai_compatible_shape() -> None:
    observed_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_request["url"] = str(request.url)
        observed_request["headers"] = dict(request.headers)
        observed_request["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": "基于证据的回答"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DeepSeekChatClient(api_key="test-key", http_client=http_client)

    result = await client.generate(
        [
            ChatMessage(role="system", content="只使用提供的证据。"),
            ChatMessage(role="user", content="知识库能做什么？"),
        ]
    )

    assert observed_request["url"] == "https://api.deepseek.com/chat/completions"
    assert observed_request["headers"]["authorization"] == "Bearer test-key"
    assert observed_request["payload"] == {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "只使用提供的证据。"},
            {"role": "user", "content": "知识库能做什么？"},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    assert result.content == "基于证据的回答"
    assert result.model == "deepseek-v4-flash"
    assert result.usage.total_tokens == 18
    await http_client.aclose()


@pytest.mark.asyncio
async def test_deepseek_client_requires_an_api_key_before_any_network_call() -> None:
    client = DeepSeekChatClient(api_key=None)

    with pytest.raises(ModelConfigurationError, match="DEEPSEEK_API_KEY"):
        await client.generate([ChatMessage(role="user", content="测试")])


@pytest.mark.asyncio
async def test_deepseek_client_does_not_return_the_upstream_body_in_errors() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(429, text="sensitive upstream payload")
        )
    )
    client = DeepSeekChatClient(api_key="test-key", http_client=http_client)

    with pytest.raises(ModelUpstreamError) as error:
        await client.generate([ChatMessage(role="user", content="测试")])

    assert "sensitive upstream payload" not in str(error.value)
    await http_client.aclose()
