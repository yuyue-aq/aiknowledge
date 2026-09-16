from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.infrastructure.database.session import Database, DatabaseUnavailable
from app.infrastructure.storage.minio import ObjectStorageError


class DependencyUnavailable(RuntimeError):
    """A required runtime dependency did not pass its safe health check."""


class ReadinessProbe(Protocol):
    async def check(self) -> None: ...


class ObjectStorageBootstrap(Protocol):
    async def ensure_bucket(self) -> None: ...


class DatabaseReadinessProbe:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def check(self) -> None:
        try:
            await self._database.ping()
        except DatabaseUnavailable as exc:
            raise DependencyUnavailable("Database is unavailable.") from exc


class ObjectStorageReadinessProbe:
    def __init__(self, storage: ObjectStorageBootstrap) -> None:
        self._storage = storage

    async def check(self) -> None:
        try:
            await self._storage.ensure_bucket()
        except ObjectStorageError as exc:
            raise DependencyUnavailable("Object storage is unavailable.") from exc


class CompositeReadinessProbe:
    """Check every mandatory dependency in a deterministic, safe order."""

    def __init__(self, *probes: ReadinessProbe) -> None:
        self._probes: Sequence[ReadinessProbe] = probes

    async def check(self) -> None:
        for probe in self._probes:
            await probe.check()
