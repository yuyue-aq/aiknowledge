from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class AnswerStatus(StrEnum):
    ANSWERED = "ANSWERED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class SourceChunk:
    id: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class Citation:
    source_chunk_id: str
    title: str
    score: float


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GeneratedText:
    content: str
    model: str
    usage: Usage = Usage()


@dataclass(slots=True)
class RagAnswer:
    status: AnswerStatus
    answer: str
    citations: list[Citation] = field(default_factory=list)
    model: str | None = None
    usage: Usage = field(default_factory=Usage)
