from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.documents import (
    DocumentStatus,
    DocumentSubmission,
    DocumentVersionStatus,
    StoredDocument,
    StoredDocumentVersion,
)
from app.main import create_app


class FakeDocumentService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        now = datetime(2026, 9, 11, tzinfo=UTC)
        self.document = StoredDocument(
            id=uuid4(),
            space_id=uuid4(),
            category_id=None,
            original_filename="资料.txt",
            storage_key="documents/private/source.txt",
            mime_type="text/plain",
            size_bytes=4,
            sha256="a" * 64,
            status=DocumentStatus.PROCESSING,
            active_version_id=None,
            created_at=now,
            updated_at=now,
        )
        self.version = StoredDocumentVersion(
            id=uuid4(),
            document_id=self.document.id,
            version_number=1,
            parser_version="mvp-parser-v1",
            embedding_provider="local",
            embedding_model="BAAI/bge-large-zh-v1.5",
            embedding_dimension=1024,
            chunk_config={},
            status=DocumentVersionStatus.PROCESSING,
            created_at=now,
        )

    async def upload(self, **kwargs: object) -> DocumentSubmission:
        self.calls.append(kwargs)
        self.document = replace(
            self.document,
            space_id=kwargs["space_id"],  # type: ignore[arg-type]
            category_id=kwargs["category_id"],  # type: ignore[arg-type]
            original_filename=kwargs["filename"],  # type: ignore[arg-type]
            size_bytes=len(kwargs["content"]),  # type: ignore[arg-type]
        )
        return DocumentSubmission(
            document=self.document, version=self.version, processing_enqueued=True
        )

    async def get_document(self, document_id: UUID) -> StoredDocument:
        assert document_id == self.document.id
        return self.document


class FakeStorage:
    async def get_bytes(self, object_key: str) -> bytes:
        assert object_key == "documents/private/source.txt"
        return b"test"


@pytest.mark.asyncio
async def test_document_upload_api_reads_multipart_file_and_returns_processing_status() -> None:
    service = FakeDocumentService()
    app = create_app(
        rag_service=object(), document_service_factory=lambda _: service
    )
    space_id = uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/spaces/{space_id}/documents",
            files={"file": ("资料.txt", b"test", "text/plain")},
        )

    assert response.status_code == 202
    assert service.calls == [
        {
            "space_id": space_id,
            "category_id": None,
            "filename": "资料.txt",
            "content": b"test",
            "content_type": "text/plain",
        }
    ]
    body = response.json()
    assert UUID(body["document"]["id"]) == service.document.id
    assert body["document"]["status"] == "PROCESSING"
    assert body["processing_enqueued"] is True
    assert "storage_key" not in body["document"]
    assert "sha256" not in body["document"]


@pytest.mark.asyncio
async def test_batch_document_upload_returns_successes_and_per_file_failures() -> None:
    service = FakeDocumentService()
    original_upload = service.upload

    async def upload_with_one_failure(**kwargs: object) -> DocumentSubmission:
        if kwargs["filename"] == "坏文件.exe":
            from app.services.document_workflow import DocumentUploadError

            raise DocumentUploadError("不支持的文件类型。")
        return await original_upload(**kwargs)

    service.upload = upload_with_one_failure  # type: ignore[method-assign]
    app = create_app(
        rag_service=object(), document_service_factory=lambda _: service
    )
    space_id = uuid4()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/api/v1/spaces/{space_id}/documents/batch",
            files=[
                ("files", ("好文件.txt", b"ok", "text/plain")),
                ("files", ("坏文件.exe", b"bad", "application/octet-stream")),
            ],
        )

    assert response.status_code == 202
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["document"]["original_filename"] == "好文件.txt"
    assert response.json()["failures"] == [
        {"filename": "坏文件.exe", "code": "DOCUMENT_UPLOAD_INVALID", "message": "不支持的文件类型。"}
    ]


@pytest.mark.asyncio
async def test_document_download_streams_private_bytes_with_safe_filename_header() -> None:
    service = FakeDocumentService()
    app = create_app(
        rag_service=object(),
        document_service_factory=lambda _: service,
        storage=FakeStorage(),  # type: ignore[arg-type]
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/documents/{service.document.id}/download")

    assert response.status_code == 200
    assert response.content == b"test"
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert "资料.txt" not in response.headers["content-disposition"]
    assert "%E8%B5%84%E6%96%99.txt" in response.headers["content-disposition"]
