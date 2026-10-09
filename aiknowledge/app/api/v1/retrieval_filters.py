from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.retrieval import RetrievalMetadataFilter


DocumentFormatFilter = Literal["pdf", "docx", "markdown", "text", "table", "presentation"]


class RetrievalMetadataFilterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_ids: list[UUID] = Field(default_factory=list, max_length=100)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    formats: list[DocumentFormatFilter] = Field(default_factory=list, max_length=6)
    version_min: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    version_max: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_domain_filter(self):
        self.to_domain()
        return self

    def to_domain(self) -> RetrievalMetadataFilter:
        return RetrievalMetadataFilter(
            category_ids=tuple(self.category_ids),
            tag_ids=tuple(self.tag_ids),
            formats=tuple(self.formats),
            version_min=self.version_min,
            version_max=self.version_max,
            valid_from=self.valid_from,
            valid_to=self.valid_to,
        )

    @classmethod
    def from_domain(cls, value: RetrievalMetadataFilter) -> "RetrievalMetadataFilterRequest":
        return cls(**value.snapshot())
