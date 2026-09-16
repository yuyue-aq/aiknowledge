from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.model import router as model_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.evaluations import router as evaluations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.spaces import router as spaces_router
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    app_error_response,
    unhandled_error_response,
    validation_error_response,
)
from app.core.request_id import RequestIdMiddleware
from app.core.security import (
    InMemoryRateLimiter,
    OriginProtectionMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.infrastructure.database.session import Database
from app.infrastructure.database.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.database.conversation_repository import SqlAlchemyConversationRepository
from app.infrastructure.database.feedback_repository import SqlAlchemyFeedbackRepository
from app.infrastructure.database.evaluation_repository import SqlAlchemyEvaluationRepository
from app.infrastructure.database.space_repository import SqlAlchemySpaceRepository
from app.infrastructure.embeddings.bge import BgeEmbeddingClient
from app.infrastructure.health import (
    CompositeReadinessProbe,
    DatabaseReadinessProbe,
    DependencyUnavailable,
    ObjectStorageReadinessProbe,
    ReadinessProbe,
)
from app.infrastructure.llm.deepseek import DeepSeekChatClient
from app.infrastructure.queue.redis import RedisReadinessProbe
from app.infrastructure.queue.document_dispatcher import CeleryDocumentDispatcher
from app.infrastructure.storage.minio import MinioObjectStorage
from app.services.rag import EvidenceRagService, RetrievalConfig
from app.services.conversations import ConversationService
from app.services.public_access import PublicSessionCodec
from app.services.feedback import FeedbackService
from app.services.evaluations import EvaluationService
from app.services.spaces import SpaceService
from app.services.document_workflow import DocumentUploadService
from app.services.document_management import (
    DocumentApplicationService,
    DocumentManagementService,
)
from app.workers.celery_app import celery_app


def create_app(
    *,
    settings: Settings | None = None,
    rag_service: EvidenceRagService | object | None = None,
    database: Database | None = None,
    storage: MinioObjectStorage | None = None,
    readiness_probe: ReadinessProbe | None = None,
    space_service_factory: Callable[[AsyncSession], object] | None = None,
    document_service_factory: Callable[[AsyncSession], object] | None = None,
    conversation_service_factory: Callable[[AsyncSession], object] | None = None,
    query_embedding_client: object | None = None,
    public_session_codec: object | None = None,
    feedback_service_factory: Callable[[AsyncSession], object] | None = None,
    evaluation_service_factory: Callable[[AsyncSession], object] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database(
        url=settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    storage = storage or MinioObjectStorage.from_settings(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        bucket_name=settings.minio_bucket,
        secure=settings.minio_secure,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await database.dispose()

    app = FastAPI(title="AiKnowledge API", version="0.1.0", lifespan=lifespan)
    allowed_origins = [
        origin.strip().rstrip("/")
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    rate_limiter = InMemoryRateLimiter(
        window_seconds=settings.public_rate_limit_window_seconds
    )
    app.add_middleware(
        OriginProtectionMiddleware,
        allowed_origins=allowed_origins,
    )
    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        limits={
            "public_session": settings.public_session_rate_limit,
            "public_question": settings.public_question_rate_limit,
        },
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(AppError, app_error_response)
    app.add_exception_handler(RequestValidationError, validation_error_response)
    app.add_exception_handler(Exception, unhandled_error_response)
    embedding_client = query_embedding_client or BgeEmbeddingClient(
        model_name=settings.bge_model_name,
        expected_dimension=settings.bge_embedding_dimension,
        use_fp16=settings.bge_use_fp16,
        batch_size=settings.bge_batch_size,
        timeout_seconds=settings.bge_timeout_seconds,
        max_retries=settings.bge_max_retries,
    )
    app.state.rag_service = rag_service or _build_rag_service(
        settings, embedding_client=embedding_client
    )
    app.state.query_embedding_client = embedding_client
    app.state.settings = settings
    app.state.rate_limiter = rate_limiter
    app.state.database = database
    app.state.storage = storage
    app.state.space_service_factory = space_service_factory or (
        lambda session: SpaceService(
            repository=SqlAlchemySpaceRepository(session),
            token_pepper=settings.share_token_pepper.get_secret_value(),
        )
    )
    def default_document_service(session: AsyncSession) -> DocumentApplicationService:
        repository = SqlAlchemyDocumentRepository(session)
        dispatcher = CeleryDocumentDispatcher(celery_app)
        return DocumentApplicationService(
            upload_service=DocumentUploadService(
                repository=repository,
                storage=storage,
                dispatcher=dispatcher,
                max_file_bytes=settings.document_max_file_bytes,
                embedding_model=settings.bge_model_name,
                embedding_dimension=settings.bge_embedding_dimension,
            ),
            management_service=DocumentManagementService(
                repository=repository,
                dispatcher=dispatcher,
            ),
        )

    app.state.document_service_factory = document_service_factory or default_document_service
    app.state.conversation_service_factory = conversation_service_factory or (
        lambda session: ConversationService(
            repository=SqlAlchemyConversationRepository(session),
            embedding_client=app.state.query_embedding_client,
            rag_service=app.state.rag_service,
            retrieval_candidate_limit=settings.retrieval_candidate_limit,
            rag_snapshot={
                "embedding_model": settings.bge_model_name,
                "embedding_dimension": settings.bge_embedding_dimension,
                "chat_model": settings.deepseek_model,
                "reranker": "noop",
            },
            retrieval_config_snapshot={
                "top_k": settings.retrieval_top_k,
                "minimum_evidence_score": settings.evidence_minimum_score,
            },
        )
    )
    app.state.public_session_codec = public_session_codec or PublicSessionCodec(
        secret=settings.public_session_secret.get_secret_value(),
        ttl_seconds=settings.public_session_ttl_seconds,
    )
    app.state.feedback_service_factory = feedback_service_factory or (
        lambda session: FeedbackService(repository=SqlAlchemyFeedbackRepository(session))
    )
    def default_evaluation_service(session: AsyncSession) -> EvaluationService:
        runner = ConversationService(
            repository=SqlAlchemyConversationRepository(session),
            embedding_client=app.state.query_embedding_client,
            rag_service=app.state.rag_service,
            retrieval_candidate_limit=settings.retrieval_candidate_limit,
            rag_snapshot={
                "embedding_model": settings.bge_model_name,
                "embedding_dimension": settings.bge_embedding_dimension,
                "chat_model": settings.deepseek_model,
                "reranker": "noop",
            },
            retrieval_config_snapshot={
                "top_k": settings.retrieval_top_k,
                "minimum_evidence_score": settings.evidence_minimum_score,
            },
        )
        return EvaluationService(
            repository=SqlAlchemyEvaluationRepository(session),
            runner=runner,
            run_snapshot={
                "embedding_model": settings.bge_model_name,
                "embedding_dimension": settings.bge_embedding_dimension,
                "chat_model": settings.deepseek_model,
                "candidate_limit": settings.retrieval_candidate_limit,
                "context_top_k": settings.retrieval_top_k,
            },
        )

    app.state.evaluation_service_factory = (
        evaluation_service_factory or default_evaluation_service
    )
    app.state.readiness_probe = readiness_probe or CompositeReadinessProbe(
        DatabaseReadinessProbe(database),
        RedisReadinessProbe(url=settings.redis_url),
        ObjectStorageReadinessProbe(storage),
    )

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        try:
            await app.state.readiness_probe.check()
        except DependencyUnavailable as exc:
            raise AppError(
                code="DEPENDENCY_NOT_READY",
                message="服务暂时不可用，请稍后重试。",
                status_code=503,
            ) from exc
        return {"status": "ok"}

    app.include_router(model_router, prefix="/api/v1")
    app.include_router(spaces_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(conversations_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(evaluations_router, prefix="/api/v1")
    return app


def _build_rag_service(
    settings: Settings, *, embedding_client: object | None = None
) -> EvidenceRagService:
    api_key = (
        settings.deepseek_api_key.get_secret_value()
        if settings.deepseek_api_key is not None
        else None
    )
    return EvidenceRagService(
        embedding_client=embedding_client  # type: ignore[arg-type]
        or BgeEmbeddingClient(
            model_name=settings.bge_model_name,
            expected_dimension=settings.bge_embedding_dimension,
            use_fp16=settings.bge_use_fp16,
            batch_size=settings.bge_batch_size,
            timeout_seconds=settings.bge_timeout_seconds,
            max_retries=settings.bge_max_retries,
        ),
        llm_client=DeepSeekChatClient(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=settings.deepseek_timeout_seconds,
            temperature=settings.answer_temperature,
            max_tokens=settings.answer_max_tokens,
            thinking_enabled=settings.deepseek_thinking_enabled,
            max_retries=settings.deepseek_max_retries,
        ),
        config=RetrievalConfig(
            top_k=settings.retrieval_top_k,
            minimum_evidence_score=settings.evidence_minimum_score,
        ),
    )


app = create_app()
