from __future__ import annotations

from io import BytesIO
from pathlib import PurePath
import re

from charset_normalizer import from_bytes
from docx import Document
from markdown_it import MarkdownIt
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.domain.documents import (
    DocumentBlock,
    DocumentFailureCode,
    DocumentFormat,
    ParsedDocument,
)


class DocumentParseError(ValueError):
    """A stable, user-safe document parsing failure."""

    def __init__(self, code: DocumentFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocumentParser:
    """Extract structured text from the four MVP document formats."""

    _FORMAT_BY_EXTENSION = {
        ".pdf": DocumentFormat.PDF,
        ".docx": DocumentFormat.DOCX,
        ".md": DocumentFormat.MARKDOWN,
        ".markdown": DocumentFormat.MARKDOWN,
        ".txt": DocumentFormat.TEXT,
    }

    def parse(self, *, filename: str, content: bytes) -> ParsedDocument:
        if not content:
            raise DocumentParseError(
                DocumentFailureCode.EMPTY_DOCUMENT, "文档内容为空，无法处理。"
            )

        document_format = self._resolve_format(filename)
        blocks = {
            DocumentFormat.PDF: self._parse_pdf,
            DocumentFormat.DOCX: self._parse_docx,
            DocumentFormat.MARKDOWN: self._parse_markdown,
            DocumentFormat.TEXT: self._parse_text,
        }[document_format](content)

        if not blocks:
            raise DocumentParseError(
                DocumentFailureCode.EMPTY_DOCUMENT,
                "未从文档中提取到可用于知识库的文本。",
            )
        return ParsedDocument(
            filename=filename,
            format=document_format,
            blocks=tuple(blocks),
        )

    def _resolve_format(self, filename: str) -> DocumentFormat:
        extension = PurePath(filename).suffix.lower()
        document_format = self._FORMAT_BY_EXTENSION.get(extension)
        if document_format is None:
            raise DocumentParseError(
                DocumentFailureCode.UNSUPPORTED_FILE_TYPE,
                "仅支持 PDF、DOCX、Markdown 和 TXT 文件。",
            )
        return document_format

    def _parse_pdf(self, content: bytes) -> list[DocumentBlock]:
        try:
            reader = PdfReader(BytesIO(content))
        except PdfReadError as exc:
            raise DocumentParseError(
                DocumentFailureCode.MALFORMED_DOCUMENT, "PDF 文件损坏或无法读取。"
            ) from exc
        if reader.is_encrypted:
            raise DocumentParseError(
                DocumentFailureCode.ENCRYPTED_PDF, "暂不支持加密 PDF，请移除密码后重新上传。"
            )

        blocks: list[DocumentBlock] = []
        try:
            for page_number, page in enumerate(reader.pages, 1):
                text = _clean_text(page.extract_text() or "")
                if text:
                    blocks.append(
                        DocumentBlock(
                            text=text,
                            heading_path=(),
                            ordinal=len(blocks) + 1,
                            page_number=page_number,
                        )
                    )
        except (PdfReadError, ValueError) as exc:
            raise DocumentParseError(
                DocumentFailureCode.MALFORMED_DOCUMENT, "PDF 文本提取失败。"
            ) from exc
        return blocks

    def _parse_docx(self, content: bytes) -> list[DocumentBlock]:
        try:
            source = Document(BytesIO(content))
        except Exception as exc:
            raise DocumentParseError(
                DocumentFailureCode.MALFORMED_DOCUMENT, "DOCX 文件损坏或无法读取。"
            ) from exc

        blocks: list[DocumentBlock] = []
        heading_path: list[str] = []
        for paragraph in source.paragraphs:
            text = _clean_text(paragraph.text)
            if not text:
                continue
            level = _heading_level(paragraph.style.name if paragraph.style else "")
            if level is not None:
                heading_path = heading_path[: level - 1]
                heading_path.append(text)
                continue
            blocks.append(
                DocumentBlock(
                    text=text,
                    heading_path=tuple(heading_path),
                    ordinal=len(blocks) + 1,
                )
            )

        for table in source.tables:
            rows = [
                " | ".join(_clean_inline_text(cell.text) for cell in row.cells)
                for row in table.rows
            ]
            table_text = _clean_text("\n".join(row for row in rows if row.strip()))
            if table_text:
                blocks.append(
                    DocumentBlock(
                        text=table_text,
                        heading_path=tuple(heading_path),
                        ordinal=len(blocks) + 1,
                    )
                )
        return blocks

    def _parse_markdown(self, content: bytes) -> list[DocumentBlock]:
        text = self._decode_text(content)
        tokens = MarkdownIt("commonmark").parse(text)
        blocks: list[DocumentBlock] = []
        heading_path: list[str] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == "heading_open" and index + 1 < len(tokens):
                inline = tokens[index + 1]
                level = int(token.tag[1:])
                heading = _clean_inline_text(inline.content)
                if heading:
                    heading_path = heading_path[: level - 1]
                    heading_path.append(heading)
                index += 3
                continue
            if token.type == "paragraph_open" and index + 1 < len(tokens):
                inline = tokens[index + 1]
                paragraph = _clean_text(inline.content)
                if paragraph:
                    blocks.append(
                        DocumentBlock(
                            text=paragraph,
                            heading_path=tuple(heading_path),
                            ordinal=len(blocks) + 1,
                        )
                    )
                index += 3
                continue
            index += 1
        return blocks

    def _parse_text(self, content: bytes) -> list[DocumentBlock]:
        text = _clean_text(self._decode_text(content))
        return [DocumentBlock(text=text, heading_path=(), ordinal=1)] if text else []

    @staticmethod
    def _decode_text(content: bytes) -> str:
        # Prefer deterministic codecs for our supported Chinese user base. The
        # library fallback covers less common encodings without exposing guesses.
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                pass
        match = from_bytes(content).best()
        if match is None:
            raise DocumentParseError(
                DocumentFailureCode.INVALID_TEXT_ENCODING,
                "无法识别 TXT 或 Markdown 文件的文本编码。",
            )
        return str(match)


def _clean_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _heading_level(style_name: str) -> int | None:
    match = re.search(r"(?:heading|标题)\s*(\d+)", style_name, re.IGNORECASE)
    return int(match.group(1)) if match else None
