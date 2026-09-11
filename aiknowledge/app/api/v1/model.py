from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domain.rag import Citation, RagAnswer, SourceChunk, Usage

router = APIRouter(tags=["model"])


class RagServicePort(Protocol):
    async def answer(self, question: str, chunks: list[SourceChunk]) -> RagAnswer: ...


class InputDocument(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=100_000)


class ModelAnswerRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=4_000)
    documents: list[InputDocument] = Field(min_length=1, max_length=12)


class CitationResponse(BaseModel):
    source_chunk_id: str
    title: str
    score: float

    @classmethod
    def from_domain(cls, citation: Citation) -> CitationResponse:
        return cls(
            source_chunk_id=citation.source_chunk_id,
            title=citation.title,
            score=citation.score,
        )


class UsageResponse(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    @classmethod
    def from_domain(cls, usage: Usage) -> UsageResponse:
        return cls(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )


class ModelAnswerResponse(BaseModel):
    status: str
    answer: str
    citations: list[CitationResponse]
    model: str | None
    usage: UsageResponse

    @classmethod
    def from_domain(cls, answer: RagAnswer) -> ModelAnswerResponse:
        return cls(
            status=answer.status.value,
            answer=answer.answer,
            citations=[CitationResponse.from_domain(item) for item in answer.citations],
            model=answer.model,
            usage=UsageResponse.from_domain(answer.usage),
        )


def get_rag_service(request: Request) -> RagServicePort:
    return request.app.state.rag_service


@router.post("/model/answer", response_model=ModelAnswerResponse)
async def answer_with_supplied_evidence(
    payload: ModelAnswerRequest,
    rag_service: Annotated[RagServicePort, Depends(get_rag_service)],
) -> ModelAnswerResponse:
    """Development-only thin vertical slice for model integration.

    It accepts caller-provided documents only until the document-storage and
    authorization milestones replace it with server-authorized RetrievalScope.
    """

    chunks = [
        SourceChunk(id=item.id, title=item.title, content=item.content)
        for item in payload.documents
    ]
    result = await rag_service.answer(payload.question, chunks)
    return ModelAnswerResponse.from_domain(result)
