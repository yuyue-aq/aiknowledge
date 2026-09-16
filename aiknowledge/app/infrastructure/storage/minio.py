from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from minio import Minio
from minio.error import InvalidResponseError, S3Error, ServerError


class ObjectStorageError(RuntimeError):
    """A sanitized object-storage failure safe for application error handling."""


class InvalidStorageKeyError(ValueError):
    """Raised before an untrusted key can reach the object storage SDK."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    etag: str | None
    version_id: str | None


class MinioClientProtocol(Protocol):
    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> None: ...

    def put_object(
        self,
        *,
        bucket_name: str,
        object_name: str,
        data: BytesIO,
        length: int,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> object: ...

    def get_object(self, *, bucket_name: str, object_name: str) -> object: ...

    def remove_object(self, *, bucket_name: str, object_name: str) -> None: ...


class MinioObjectStorage:
    """Async boundary over MinIO's synchronous, private-bucket SDK client."""

    def __init__(
        self,
        *,
        bucket_name: str,
        client_factory: Callable[[], MinioClientProtocol] | None = None,
    ) -> None:
        if not bucket_name.strip():
            raise ValueError("bucket_name must not be empty")
        self._bucket_name = bucket_name
        self._client_factory = client_factory or self._missing_client_factory
        self._client: MinioClientProtocol | None = None

    @classmethod
    def from_settings(
        cls,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool,
    ) -> "MinioObjectStorage":
        """Construct the production adapter without exposing credentials elsewhere."""

        return cls(
            bucket_name=bucket_name,
            client_factory=lambda: Minio(
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure,
            ),
        )

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket_sync)

    async def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        self._validate_object_key(object_key)
        if not content_type.strip():
            raise ValueError("content_type must not be empty")
        await self.ensure_bucket()
        return await asyncio.to_thread(
            self._put_bytes_sync,
            object_key,
            data,
            content_type,
            dict(metadata) if metadata is not None else None,
        )

    async def get_bytes(self, object_key: str) -> bytes:
        self._validate_object_key(object_key)
        return await asyncio.to_thread(self._get_bytes_sync, object_key)

    async def delete(self, object_key: str) -> None:
        self._validate_object_key(object_key)
        await asyncio.to_thread(self._delete_sync, object_key)

    def _get_client(self) -> MinioClientProtocol:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _ensure_bucket_sync(self) -> None:
        client = self._get_client()
        try:
            if client.bucket_exists(self._bucket_name):
                return
            try:
                client.make_bucket(self._bucket_name)
            except S3Error:
                # A concurrent API/worker process may have won the creation
                # race. Re-check before surfacing a failure.
                if not client.bucket_exists(self._bucket_name):
                    raise
        except (S3Error, InvalidResponseError, ServerError) as exc:
            raise ObjectStorageError("Object storage bucket is unavailable.") from exc

    def _put_bytes_sync(
        self,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None,
    ) -> StoredObject:
        try:
            result = self._get_client().put_object(
                bucket_name=self._bucket_name,
                object_name=object_key,
                data=BytesIO(data),
                length=len(data),
                content_type=content_type,
                metadata=metadata,
            )
        except (S3Error, InvalidResponseError, ServerError) as exc:
            raise ObjectStorageError("Unable to store the private document.") from exc
        return StoredObject(
            object_key=object_key,
            etag=getattr(result, "etag", None),
            version_id=getattr(result, "version_id", None),
        )

    def _get_bytes_sync(self, object_key: str) -> bytes:
        response: object | None = None
        try:
            response = self._get_client().get_object(
                bucket_name=self._bucket_name,
                object_name=object_key,
            )
            read = getattr(response, "read")
            return read()
        except (S3Error, InvalidResponseError, ServerError) as exc:
            raise ObjectStorageError("Unable to read the private document.") from exc
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

    def _delete_sync(self, object_key: str) -> None:
        try:
            self._get_client().remove_object(
                bucket_name=self._bucket_name,
                object_name=object_key,
            )
        except (S3Error, InvalidResponseError, ServerError) as exc:
            raise ObjectStorageError("Unable to delete the private document.") from exc

    @staticmethod
    def _validate_object_key(object_key: str) -> None:
        parts = object_key.split("/")
        if (
            not object_key
            or object_key != object_key.strip()
            or object_key.startswith(("/", "\\"))
            or "\\" in object_key
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise InvalidStorageKeyError("Object storage key is invalid.")

    @staticmethod
    def _missing_client_factory() -> MinioClientProtocol:
        raise RuntimeError("MinIO client factory was not configured.")
