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
    answer_temperature: float = Field(default=0.2, ge=0, le=2)
    answer_max_tokens: int = Field(default=1200, ge=1, le=384000)

    bge_model_name: str = "BAAI/bge-large-zh-v1.5"
    # The official model card reports a 1024-dimensional output for this model.
    bge_embedding_dimension: int = Field(default=1024, gt=0)
    bge_use_fp16: bool = False

    retrieval_top_k: int = Field(default=4, ge=1, le=20)
    # No global production threshold is hard-coded. It must be calibrated with
    # the project's evaluation set before the persisted-RAG milestone ships.
    evidence_minimum_score: float | None = Field(default=None, ge=-1, le=1)


def get_settings() -> Settings:
    """Create settings at the composition root rather than at import time."""

    return Settings()
