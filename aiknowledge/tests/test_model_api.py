from __future__ import annotations

import httpx
import pytest

from app.domain.rag import AnswerStatus, Citation, RagAnswer, Usage
from app.main import create_app


class StubRagService:
    def __init__(self) -> None:
        self.question: str | None = None
        self.chunks = []

    async def answer(self, question: str, chunks):  # type: ignore[no-untyped-def]
        self.question = question
        self.chunks = chunks
        return RagAnswer(
            status=AnswerStatus.ANSWERED,
            answer="已根据提供资料回答。",
            citations=[Citation(source_chunk_id="guide", title="指南", score=0.91)],
            model="deepseek-v4-flash",
            usage=Usage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )


@pytest.mark.asyncio
async def test_model_answer_endpoint_delegates_to_the_rag_service() -> None:
    service = StubRagService()
    app = create_app(rag_service=service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/model/answer",
            json={
                "question": "知识库有什么能力？",
                "documents": [
                    {"id": "guide", "title": "指南", "content": "这里是可检索资料。"}
                ],
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ANSWERED",
        "answer": "已根据提供资料回答。",
        "citations": [{"source_chunk_id": "guide", "title": "指南", "score": 0.91}],
        "model": "deepseek-v4-flash",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }
    assert service.question == "知识库有什么能力？"
    assert service.chunks[0].id == "guide"


@pytest.mark.asyncio
async def test_model_answer_endpoint_rejects_an_empty_document_list() -> None:
    app = create_app(rag_service=StubRagService())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/model/answer", json={"question": "问题", "documents": []}
        )

    assert response.status_code == 422
