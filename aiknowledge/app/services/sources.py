from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from io import BytesIO
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from app.domain.sources import (
    KnowledgeSource,
    SourceDocument,
    SourceKind,
    SourceStatus,
    SourceSyncResult,
)
from app.domain.users import SpaceRole


class SourceRepository(Protocol):
    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def add_source(self, source: KnowledgeSource) -> None: ...

    async def list_sources(self, space_id: UUID) -> list[KnowledgeSource]: ...

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None: ...

    async def update_source(self, source: KnowledgeSource) -> None: ...

    async def commit(self) -> None: ...


class SourceFetcher(Protocol):
    async def fetch(self, source: KnowledgeSource) -> tuple[SourceDocument, ...]: ...


class SourceUploader(Protocol):
    async def upload(
        self,
        *,
        space_id: UUID,
        category_id: UUID | None,
        document: SourceDocument,
        owner_user_id: UUID | None,
    ) -> object: ...


class DocumentSourceUploader:
    """Adapt the document application service to the source sync port."""

    def __init__(self, document_service: object) -> None:
        self._document_service = document_service

    async def upload(
        self,
        *,
        space_id: UUID,
        category_id: UUID | None,
        document: SourceDocument,
        owner_user_id: UUID | None,
    ) -> object:
        upload = getattr(self._document_service, "upload", None)
        if upload is None:
            raise TypeError("document service does not support uploads")
        return await upload(
            space_id=space_id,
            category_id=category_id,
            filename=document.filename,
            content=document.content,
            content_type=document.content_type,
            owner_user_id=owner_user_id,
        )


class SourceAccessDeniedError(PermissionError):
    pass


class SourceNotFoundError(LookupError):
    pass


class SourceSyncError(RuntimeError):
    pass


class HttpSourceFetcher:
    """Fetch a URL as a safe text document for the first sync iteration."""

    def __init__(self, *, timeout_seconds: float = 30, max_bytes: int = 20 * 1024 * 1024) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    async def fetch(self, source: KnowledgeSource) -> tuple[SourceDocument, ...]:
        import httpx

        parsed = urlparse(source.locator)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise SourceSyncError("来源地址必须是 http 或 https URL。")
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "AiKnowledge-source-sync/1.0"},
        ) as client:
            response = await client.get(source.locator)
            response.raise_for_status()
            content = response.content
        if len(content) > self._max_bytes:
            raise SourceSyncError("来源内容超过同步大小上限。")
        content_type = response.headers.get("content-type", "text/plain").split(";", 1)[0]
        if source.kind is SourceKind.MARKDOWN_REPOSITORY and (
            "zip" in content_type or source.locator.lower().endswith(".zip")
        ):
            documents = _markdown_documents_from_archive(content)
            if documents:
                return documents
            raise SourceSyncError("Markdown 仓库中没有可导入的 Markdown 文件。")
        if source.kind is SourceKind.FAQ_TABLE:
            locator_lower = source.locator.lower()
            if "spreadsheetml.sheet" in content_type or locator_lower.endswith(".xlsx"):
                extension = ".xlsx"
                mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                extension = ".tsv" if "tab-separated" in content_type else ".csv"
                mime = "text/tab-separated-values" if extension == ".tsv" else "text/csv"
            return (SourceDocument(filename=f"faq{extension}", content=content, content_type=mime),)
        if source.kind is SourceKind.MARKDOWN_REPOSITORY or "markdown" in content_type:
            return (SourceDocument(filename="source.md", content=content, content_type="text/markdown"),)
        return (SourceDocument(filename="source.txt", content=content, content_type="text/plain"),)


def _markdown_documents_from_archive(content: bytes) -> tuple[SourceDocument, ...]:
    """Extract safe, bounded Markdown files from a repository archive."""

    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise SourceSyncError("Markdown 仓库压缩包无效。") from exc
    documents: list[SourceDocument] = []
    with archive:
        for member in archive.infolist():
            if member.is_dir() or len(documents) >= 200:
                continue
            filename = member.filename.replace("\\", "/")
            if filename.startswith("/") or ".." in filename.split("/"):
                continue
            if not filename.lower().endswith((".md", ".markdown")):
                continue
            if member.file_size <= 0 or member.file_size > 20 * 1024 * 1024:
                continue
            documents.append(
                SourceDocument(
                    filename=filename,
                    content=archive.read(member),
                    content_type="text/markdown",
                )
            )
    return tuple(documents)


class SourceSyncService:
    """Manage external source definitions and deterministic manual syncs."""

    def __init__(
        self,
        *,
        repository: SourceRepository,
        fetcher: SourceFetcher,
        uploader: SourceUploader,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._fetcher = fetcher
        self._uploader = uploader
        self._id_factory = id_factory
        self._clock = clock

    async def create_source(
        self,
        *,
        space_id: UUID,
        kind: SourceKind,
        locator: str,
        name: str | None = None,
        owner_user_id: UUID | None = None,
    ) -> KnowledgeSource:
        await self._require_role(space_id, owner_user_id, minimum=SpaceRole.EDITOR)
        normalized_locator = locator.strip()
        parsed = urlparse(normalized_locator)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("来源地址必须是 http 或 https URL。")
        if len(normalized_locator) > 2_000:
            raise ValueError("来源地址不能超过 2000 个字符。")
        normalized_name = name.strip() if name is not None else None
        if normalized_name == "":
            normalized_name = None
        if normalized_name is not None and len(normalized_name) > 120:
            raise ValueError("来源名称不能超过 120 个字符。")
        now = self._now()
        source = KnowledgeSource(
            id=self._id_factory(),
            space_id=space_id,
            kind=kind,
            locator=normalized_locator,
            name=normalized_name,
            status=SourceStatus.ACTIVE,
            last_checksum=None,
            last_synced_at=None,
            last_error=None,
            created_at=now,
            updated_at=now,
        )
        await self._repository.add_source(source)
        await self._repository.commit()
        return source

    async def list_sources(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> list[KnowledgeSource]:
        await self._require_role(space_id, owner_user_id, minimum=SpaceRole.MEMBER)
        return await self._repository.list_sources(space_id)

    async def set_status(
        self, source_id: UUID, *, status: SourceStatus, owner_user_id: UUID | None = None
    ) -> KnowledgeSource:
        source = await self._get_source(source_id)
        await self._require_role(source.space_id, owner_user_id, minimum=SpaceRole.EDITOR)
        if status not in {SourceStatus.ACTIVE, SourceStatus.DISABLED}:
            raise ValueError("来源只能设置为启用或停用。")
        updated = replace(source, status=status, updated_at=self._now())
        await self._repository.update_source(updated)
        await self._repository.commit()
        return updated

    async def sync_source(
        self, source_id: UUID, *, owner_user_id: UUID | None = None
    ) -> SourceSyncResult:
        source = await self._get_source(source_id)
        await self._require_role(source.space_id, owner_user_id, minimum=SpaceRole.EDITOR)
        if source.status is SourceStatus.DISABLED:
            raise SourceSyncError("来源已停用，请先重新启用。")
        syncing = replace(source, status=SourceStatus.SYNCING, updated_at=self._now(), last_error=None)
        await self._repository.update_source(syncing)
        await self._repository.commit()
        try:
            documents = await self._fetcher.fetch(source)
            self._validate_documents(documents)
        except Exception as exc:
            failed = replace(
                syncing,
                status=SourceStatus.FAILED,
                last_error="来源同步失败，请检查地址和权限。",
                updated_at=self._now(),
            )
            await self._repository.update_source(failed)
            await self._repository.commit()
            if isinstance(exc, SourceSyncError):
                raise exc
            raise SourceSyncError("来源同步失败，请检查地址和权限。") from exc
        checksum = _documents_checksum(documents)
        if source.last_checksum == checksum:
            ready = replace(
                syncing,
                status=SourceStatus.READY,
                last_checksum=checksum,
                last_synced_at=source.last_synced_at or self._now(),
                updated_at=self._now(),
            )
            await self._repository.update_source(ready)
            await self._repository.commit()
            return SourceSyncResult(source=ready, uploaded=0, failed=0, skipped=True)
        uploaded = 0
        failed_count = 0
        for document in documents:
            try:
                await self._uploader.upload(
                    space_id=source.space_id,
                    category_id=document.category_id,
                    document=document,
                    owner_user_id=owner_user_id,
                )
            except Exception:
                failed_count += 1
            else:
                uploaded += 1
        final_status = SourceStatus.READY if uploaded else SourceStatus.FAILED
        final = replace(
            syncing,
            status=final_status,
            last_checksum=checksum if uploaded else source.last_checksum,
            last_synced_at=self._now() if uploaded else source.last_synced_at,
            last_error=("部分文档同步失败。" if failed_count else None),
            updated_at=self._now(),
        )
        await self._repository.update_source(final)
        await self._repository.commit()
        if not uploaded:
            raise SourceSyncError("来源同步失败，未导入任何文档。")
        return SourceSyncResult(
            source=final, uploaded=uploaded, failed=failed_count, skipped=False
        )

    async def _get_source(self, source_id: UUID) -> KnowledgeSource:
        source = await self._repository.get_source(source_id)
        if source is None:
            raise SourceNotFoundError("知识来源不存在。")
        return source

    async def _require_role(
        self, space_id: UUID, user_id: UUID | None, *, minimum: SpaceRole
    ) -> None:
        if user_id is None:
            return
        role = await self._repository.get_space_role(space_id=space_id, user_id=user_id)
        if role is None:
            raise SourceNotFoundError("知识空间不存在。")
        if _role_rank(role) < _role_rank(minimum):
            raise SourceAccessDeniedError("当前成员没有管理知识来源的权限。")

    @staticmethod
    def _validate_documents(documents: Sequence[SourceDocument]) -> None:
        if not documents or len(documents) > 200:
            raise SourceSyncError("来源未返回可导入文档。")
        total = 0
        for document in documents:
            if not document.filename or len(document.filename) > 255:
                raise SourceSyncError("来源返回了无效文件名。")
            if not document.content or len(document.content) > 20 * 1024 * 1024:
                raise SourceSyncError("来源返回了空文档或超大文档。")
            total += len(document.content)
        if total > 100 * 1024 * 1024:
            raise SourceSyncError("来源批量内容超过同步大小上限。")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _documents_checksum(documents: Sequence[SourceDocument]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: item.filename):
        digest.update(document.filename.encode("utf-8"))
        digest.update(b"\0")
        digest.update(document.content)
        digest.update(b"\0")
    return digest.hexdigest()


def _role_rank(role: SpaceRole) -> int:
    return {SpaceRole.MEMBER: 1, SpaceRole.EDITOR: 2, SpaceRole.OWNER: 3}[role]
