from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.infrastructure.storage.minio import (
    InvalidStorageKeyError,
    MinioObjectStorage,
)


@dataclass(slots=True)
class FakePutResult:
    object_name: str
    etag: str = "etag-123"
    version_id: str | None = "version-123"


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        self.closed = True


class FakeMinioClient:
    def __init__(self, *, bucket_exists: bool = False) -> None:
        self._bucket_exists = bucket_exists
        self.made_buckets: list[str] = []
        self.uploads: list[dict[str, object]] = []
        self.objects: dict[str, bytes] = {}
        self.last_response: FakeResponse | None = None
        self.deleted: list[str] = []

    def bucket_exists(self, bucket_name: str) -> bool:
        return self._bucket_exists

    def make_bucket(self, bucket_name: str) -> None:
        self._bucket_exists = True
        self.made_buckets.append(bucket_name)

    def put_object(
        self,
        *,
        bucket_name: str,
        object_name: str,
        data: object,
        length: int,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> FakePutResult:
        content = data.read()  # type: ignore[union-attr]
        self.objects[object_name] = content
        self.uploads.append(
            {
                "bucket_name": bucket_name,
                "object_name": object_name,
                "length": length,
                "content_type": content_type,
                "metadata": metadata,
                "content": content,
            }
        )
        return FakePutResult(object_name=object_name)

    def get_object(self, *, bucket_name: str, object_name: str) -> FakeResponse:
        response = FakeResponse(self.objects[object_name])
        self.last_response = response
        return response

    def remove_object(self, *, bucket_name: str, object_name: str) -> None:
        self.deleted.append(object_name)
        self.objects.pop(object_name, None)


@pytest.mark.asyncio
async def test_minio_storage_creates_private_bucket_and_uploads_bytes() -> None:
    client = FakeMinioClient(bucket_exists=False)
    storage = MinioObjectStorage(
        bucket_name="aiknowledge-private",
        client_factory=lambda: client,
    )

    stored = await storage.put_bytes(
        object_key="documents/abc/source.pdf",
        data=b"private source file",
        content_type="application/pdf",
        metadata={"sha256": "safe-hash"},
    )

    assert client.made_buckets == ["aiknowledge-private"]
    assert client.uploads == [
        {
            "bucket_name": "aiknowledge-private",
            "object_name": "documents/abc/source.pdf",
            "length": len(b"private source file"),
            "content_type": "application/pdf",
            "metadata": {"sha256": "safe-hash"},
            "content": b"private source file",
        }
    ]
    assert stored.object_key == "documents/abc/source.pdf"
    assert stored.etag == "etag-123"
    assert stored.version_id == "version-123"


@pytest.mark.asyncio
async def test_minio_storage_reads_bytes_and_closes_response() -> None:
    client = FakeMinioClient(bucket_exists=True)
    client.objects["documents/abc/source.txt"] = b"only the worker can read this"
    storage = MinioObjectStorage(
        bucket_name="aiknowledge-private",
        client_factory=lambda: client,
    )

    result = await storage.get_bytes("documents/abc/source.txt")

    assert result == b"only the worker can read this"
    assert client.last_response is not None
    assert client.last_response.closed is True


@pytest.mark.asyncio
async def test_minio_storage_deletes_an_existing_private_object() -> None:
    client = FakeMinioClient(bucket_exists=True)
    client.objects["documents/abc/source.txt"] = b"remove me"
    storage = MinioObjectStorage(
        bucket_name="aiknowledge-private",
        client_factory=lambda: client,
    )

    await storage.delete("documents/abc/source.txt")

    assert client.deleted == ["documents/abc/source.txt"]
    assert client.objects == {}


@pytest.mark.asyncio
async def test_minio_storage_rejects_untrusted_or_path_traversal_keys() -> None:
    client = FakeMinioClient(bucket_exists=True)
    storage = MinioObjectStorage(
        bucket_name="aiknowledge-private",
        client_factory=lambda: client,
    )

    with pytest.raises(InvalidStorageKeyError):
        await storage.put_bytes(
            object_key="../private-file.pdf",
            data=b"not uploaded",
            content_type="application/pdf",
        )

    assert client.uploads == []
