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
async def test_owned_client_bounds_connection_wait_without_shortening_generation(monkeypatch):
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]}))
    owned=httpx.AsyncClient(transport=transport)
    observed=[]
    def factory(*,timeout):
        observed.append(timeout)
        return owned
    monkeypatch.setattr(httpx,'AsyncClient',factory)
    client=DeepSeekChatClient(api_key='test',timeout_seconds=60)
    try:
        await client.generate([ChatMessage(role='user',content='test')])
        assert isinstance(observed[0],httpx.Timeout)
        assert observed[0].connect == 10
        assert observed[0].read == 60
    finally:
        await client.aclose()


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
        "model": "deepseek-flash",
        "messages": [
            {"role": "system", "content": "只使用提供的证据。"},
            {"role": "user", "content": "知识库能做什么？"},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
    }
    assert result.content == "基于证据的回答"
    assert result.model == "deepseek-v4-flash"
    assert result.usage.total_tokens == 18
    await http_client.aclose()


def test_settings_default_to_official_flash_model() -> None:
    from app.core.config import Settings

    assert Settings(_env_file=None).deepseek_model == "deepseek-flash"


@pytest.mark.asyncio
async def test_deepseek_client_explicitly_enables_thinking_when_configured() -> None:
    observed_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed_request["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"model": "deepseek-flash", "choices": [{"message": {"content": "回答"}}]},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DeepSeekChatClient(
        api_key="test-key",
        thinking_enabled=True,
        http_client=http_client,
    )

    await client.generate([ChatMessage(role="user", content="测试")])

    assert observed_request["payload"]["thinking"] == {"type": "enabled"}  # type: ignore[index]
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


@pytest.mark.asyncio
async def test_deepseek_client_retries_transient_status_with_a_bounded_attempt_count() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporary upstream failure")
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": "重试后回答"}}],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = DeepSeekChatClient(
        api_key="test-key",
        http_client=http_client,
        max_retries=1,
        retry_backoff_seconds=0,
    )

    result = await client.generate([ChatMessage(role="user", content="重试测试")])

    assert result.content == "重试后回答"
    assert attempts == 2
    await http_client.aclose()
