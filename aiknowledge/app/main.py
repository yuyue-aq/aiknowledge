from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.model import router as model_router
from app.core.config import Settings, get_settings
from app.infrastructure.embeddings.bge import BgeEmbeddingClient
from app.infrastructure.llm.deepseek import DeepSeekChatClient
from app.services.rag import EvidenceRagService, RetrievalConfig


def create_app(
    *,
    settings: Settings | None = None,
    rag_service: EvidenceRagService | object | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="AiKnowledge API", version="0.1.0")
    app.state.rag_service = rag_service or _build_rag_service(settings)

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(model_router, prefix="/api/v1")
    return app


def _build_rag_service(settings: Settings) -> EvidenceRagService:
    api_key = (
        settings.deepseek_api_key.get_secret_value()
        if settings.deepseek_api_key is not None
        else None
    )
    return EvidenceRagService(
        embedding_client=BgeEmbeddingClient(
            model_name=settings.bge_model_name,
            expected_dimension=settings.bge_embedding_dimension,
            use_fp16=settings.bge_use_fp16,
        ),
        llm_client=DeepSeekChatClient(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            temperature=settings.answer_temperature,
            max_tokens=settings.answer_max_tokens,
            thinking_enabled=settings.deepseek_thinking_enabled,
        ),
        config=RetrievalConfig(
            top_k=settings.retrieval_top_k,
            minimum_evidence_score=settings.evidence_minimum_score,
        ),
    )


app = create_app()
