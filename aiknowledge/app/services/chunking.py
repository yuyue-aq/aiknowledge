from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    content: str


class TextChunker:
    """A deterministic, CJK-friendly character chunker for the MVP pipeline."""

    _SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；!?;])")

    def __init__(self, *, max_characters: int = 1800, overlap_characters: int = 240) -> None:
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        if overlap_characters < 0 or overlap_characters >= max_characters:
            raise ValueError("overlap_characters must be smaller than max_characters")

        self._max_characters = max_characters
        self._overlap_characters = overlap_characters

    def split(self, text: str) -> list[TextChunk]:
        normalized = self._normalize(text)
        if not normalized:
            return []

        units = self._units(normalized)
        chunks: list[str] = []
        current = ""
        for unit in units:
            for piece in self._split_oversized_unit(unit):
                if not current:
                    current = piece
                    continue

                if len(current) + len(piece) <= self._max_characters:
                    current += piece
                    continue

                chunks.append(current)
                current = self._tail(current) + piece
                if len(current) > self._max_characters:
                    chunks.append(current[: self._max_characters])
                    current = self._tail(current[: self._max_characters]) + current[
                        self._max_characters :
                    ]

        if current:
            chunks.append(current)

        return [TextChunk(ordinal=index, content=chunk) for index, chunk in enumerate(chunks, 1)]

    @staticmethod
    def _normalize(text: str) -> str:
        lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
        return "\n".join(lines).strip()

    def _units(self, text: str) -> list[str]:
        units: list[str] = []
        for paragraph in re.split(r"\n{2,}", text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            sentences = [segment for segment in self._SENTENCE_BOUNDARY.split(paragraph) if segment]
            units.extend(sentences or [paragraph])
        return units

    def _split_oversized_unit(self, unit: str) -> list[str]:
        if len(unit) <= self._max_characters:
            return [unit]
        return [
            unit[index : index + self._max_characters]
            for index in range(0, len(unit), self._max_characters)
        ]

    def _tail(self, text: str) -> str:
        if self._overlap_characters == 0:
            return ""
        return text[-self._overlap_characters :]
