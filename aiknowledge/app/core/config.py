from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the first model-integration milestone.

    A missing DeepSeek key is intentional in local development: the service can
    be exercised completely with fakes, while a real request fails before any
    outbound network call.  Secrets are never part of a response model.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="AIKNOWLEDGE_",
        extra="ignore",
    )

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_thinking_enabled: bool = False
    deepseek_timeout_seconds: float = Field(default=60.0, gt=0)
    deepseek_max_retries: int = Field(default=1, ge=0, le=3)
    answer_temperature: float = Field(default=0.2, ge=0, le=2)
    answer_max_tokens: int = Field(default=1200, ge=1, le=384000)

    bge_model_name: str = "BAAI/bge-large-zh-v1.5"
    # The official model card reports a 1024-dimensional output for this model.
    bge_embedding_dimension: int = Field(default=1024, gt=0)
    bge_use_fp16: bool = False
    bge_batch_size: int = Field(default=8, ge=1, le=128)
    bge_timeout_seconds: float = Field(default=600.0, gt=0)
    bge_max_retries: int = Field(default=1, ge=0, le=3)

    retrieval_top_k: int = Field(default=4, ge=1, le=20)
    retrieval_candidate_limit: int = Field(default=12, ge=1, le=50)
    # No global production threshold is hard-coded. It must be calibrated with
    # the project's evaluation set before the persisted-RAG milestone ships.
    evidence_minimum_score: float | None = Field(default=None, ge=-1, le=1)

    database_url: str = (
        "postgresql+asyncpg://aiknowledge:aiknowledge@localhost:5432/aiknowledge"
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)

    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "aiknowledge"
    # This is a local-development default only. Deployments must inject an
    # environment-specific secret and never commit it to source control.
    minio_secret_key: SecretStr = SecretStr("aiknowledge-local-dev-secret")
    minio_bucket: str = "aiknowledge-private"
    minio_secure: bool = False

    # Kept separate from storage credentials so share links remain revocable
    # without changing the object-store account. Replace in deployment.
    share_token_pepper: SecretStr = SecretStr("aiknowledge-local-share-token-pepper")
    public_session_secret: SecretStr = SecretStr(
        "aiknowledge-local-public-session-secret"
    )
    public_session_ttl_seconds: int = Field(default=3_600, ge=60, le=86_400)
    # Local H5 runs on HTTP; deployment must set this to true behind HTTPS.
    public_session_cookie_secure: bool = False

    # Comma-separated development origins; production should inject the exact
    # deployed frontend origin(s) rather than using a wildcard with cookies.
    cors_allowed_origins: str = (
        "http://localhost:10086,http://127.0.0.1:10086,"
        "http://localhost:10080,http://127.0.0.1:10080"
    )

    # Anonymous public entry points are protected per API process.  A
    # multi-process deployment should provide a Redis-backed limiter with the
    # same policy before increasing these values.
    public_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    public_session_rate_limit: int = Field(default=20, ge=1, le=10_000)
    public_question_rate_limit: int = Field(default=60, ge=1, le=10_000)

    document_max_file_bytes: int = Field(default=20 * 1024 * 1024, ge=1)


def get_settings() -> Settings:
    """Create settings at the composition root rather than at import time."""

    return Settings()
