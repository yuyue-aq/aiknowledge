from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest

from app.domain.sources import (
    KnowledgeSource,
    SourceDocument,
    SourceKind,
    SourceStatus,
)
from app.domain.users import SpaceRole
from app.services.sources import (
    _markdown_documents_from_archive,
    SourceAccessDeniedError,
    SourceSyncService,
    SourceSyncError,
)


class FakeSourceRepository:
    def __init__(self, role: SpaceRole | None = SpaceRole.OWNER) -> None:
        self.role = role
        self.sources: dict[UUID, KnowledgeSource] = {}
        self.commits = 0

    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None:
        return self.role

    async def add_source(self, source: KnowledgeSource) -> None:
        self.sources[source.id] = source

    async def list_sources(self, space_id: UUID) -> list[KnowledgeSource]:
        return [source for source in self.sources.values() if source.space_id == space_id]

    async def get_source(self, source_id: UUID) -> KnowledgeSource | None:
        return self.sources.get(source_id)

    async def update_source(self, source: KnowledgeSource) -> None:
        self.sources[source.id] = source

    async def commit(self) -> None:
        self.commits += 1


class FakeFetcher:
    def __init__(self, documents: tuple[SourceDocument, ...]) -> None:
        self.documents = documents
        self.calls: list[KnowledgeSource] = []

    async def fetch(self, source: KnowledgeSource) -> tuple[SourceDocument, ...]:
        self.calls.append(source)
        return self.documents


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[UUID, SourceDocument]] = []

    async def upload(self, *, space_id: UUID, category_id: UUID | None, document: SourceDocument, owner_user_id: UUID | None):
        self.uploads.append((space_id, document))


def create_service(repository: FakeSourceRepository, fetcher: FakeFetcher, uploader: FakeUploader) -> SourceSyncService:
    return SourceSyncService(
        repository=repository,
        fetcher=fetcher,
        uploader=uploader,
        id_factory=uuid4,
        clock=lambda: datetime(2026, 9, 17, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_source_registration_normalizes_url_and_requires_editor() -> None:
    repository = FakeSourceRepository(role=SpaceRole.EDITOR)
    service = create_service(repository, FakeFetcher(()), FakeUploader())
    space_id = uuid4()
    source = await service.create_source(
        space_id=space_id,
        kind=SourceKind.WEBPAGE,
        locator="  https://example.com/handbook  ",
        name="产品手册",
        owner_user_id=uuid4(),
    )
    assert source.locator == "https://example.com/handbook"
    assert source.status is SourceStatus.ACTIVE
    repository.role = SpaceRole.MEMBER
    with pytest.raises(SourceAccessDeniedError, match="权限"):
        await service.create_source(
            space_id=space_id,
            kind=SourceKind.WEBPAGE,
            locator="https://example.com/other",
            owner_user_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_source_sync_uploads_documents_and_persists_checksum() -> None:
    repository = FakeSourceRepository()
    fetcher = FakeFetcher(
        (
            SourceDocument(filename="faq.csv", content="问题,答案\n如何登录?,邮箱登录".encode(), content_type="text/csv"),
            SourceDocument(filename="guide.md", content="# 指南\n正文".encode(), content_type="text/markdown"),
        )
    )
    uploader = FakeUploader()
    service = create_service(repository, fetcher, uploader)
    source = await service.create_source(
        space_id=uuid4(),
        kind=SourceKind.FAQ_TABLE,
        locator="https://example.com/faq.csv",
        owner_user_id=uuid4(),
    )

    result = await service.sync_source(source.id, owner_user_id=uuid4())
    assert result.uploaded == 2
    assert result.skipped is False
    assert repository.sources[source.id].status is SourceStatus.READY
    assert repository.sources[source.id].last_checksum
    assert len(uploader.uploads) == 2

    again = await service.sync_source(source.id, owner_user_id=uuid4())
    assert again.skipped is True
    assert len(uploader.uploads) == 2


@pytest.mark.asyncio
async def test_source_sync_marks_failure_and_hides_fetcher_details() -> None:
    class FailingFetcher(FakeFetcher):
        async def fetch(self, source: KnowledgeSource) -> tuple[SourceDocument, ...]:
            raise RuntimeError("secret upstream token")

    repository = FakeSourceRepository()
    source = KnowledgeSource(
        id=uuid4(), space_id=uuid4(), kind=SourceKind.MARKDOWN_REPOSITORY,
        locator="https://example.com/repo", name=None, status=SourceStatus.ACTIVE,
        last_checksum=None, last_synced_at=None, last_error=None,
        created_at=datetime(2026, 9, 17, tzinfo=UTC), updated_at=datetime(2026, 9, 17, tzinfo=UTC),
    )
    repository.sources[source.id] = source
    service = create_service(repository, FailingFetcher(()), FakeUploader())
    with pytest.raises(SourceSyncError, match="同步失败"):
        await service.sync_source(source.id, owner_user_id=uuid4())
    assert repository.sources[source.id].status is SourceStatus.FAILED
    assert "secret" not in (repository.sources[source.id].last_error or "")


def test_markdown_archive_extraction_ignores_unsafe_and_non_markdown_entries() -> None:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("README.md", "# 介绍")
        archive.writestr("docs/guide.markdown", "# 指南")
        archive.writestr("docs/data.csv", "a,b")
        archive.writestr("../secrets.md", "不要导入")
    documents = _markdown_documents_from_archive(stream.getvalue())
    assert [item.filename for item in documents] == ["README.md", "docs/guide.markdown"]
