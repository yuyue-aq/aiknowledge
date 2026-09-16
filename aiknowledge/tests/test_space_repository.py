from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.spaces import (
    Category,
    KnowledgeSpace,
    ShareLink,
    ShareLinkStatus,
    SpaceVisibility,
)
from app.infrastructure.database.models import CategoryRecord, KnowledgeSpaceRecord
from app.infrastructure.database.space_repository import SqlAlchemySpaceRepository


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[type, dict[object, object]] = {}
        self.added: list[object] = []
        self.executed: list[tuple[object, object]] = []
        self.flushes = 0
        self.events: list[str] = []

    def add(self, record: object) -> None:
        self.events.append("add")
        self.added.append(record)
        self.records.setdefault(type(record), {})[record.id] = record  # type: ignore[attr-defined]

    async def get(self, model: type, record_id: object) -> object | None:
        return self.records.get(model, {}).get(record_id)

    async def flush(self) -> None:
        self.events.append("flush")
        self.flushes += 1

    async def execute(self, statement: object, params: object = None) -> object:
        self.events.append("execute")
        self.executed.append((statement, params))
        return object()


@pytest.mark.asyncio
async def test_sqlalchemy_space_repository_maps_domain_space_and_category_records() -> None:
    session = FakeSession()
    repository = SqlAlchemySpaceRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    space = KnowledgeSpace(
        id=uuid4(),
        name="产品资料",
        description="可信问答",
        visibility=SpaceVisibility.PUBLIC,
        guest_feedback_enabled=True,
        created_at=now,
        updated_at=now,
    )
    category = Category(
        id=uuid4(),
        space_id=space.id,
        name="说明",
        description=None,
        is_open=True,
        sort_order=2,
        created_at=now,
        updated_at=now,
    )

    await repository.add_space(space)
    await repository.add_category(category)

    assert isinstance(session.added[0], KnowledgeSpaceRecord)
    assert session.added[0].visibility is SpaceVisibility.PUBLIC  # type: ignore[attr-defined]
    assert isinstance(session.added[1], CategoryRecord)
    assert session.added[1].space_id == space.id  # type: ignore[attr-defined]
    assert await repository.get_space(space.id) == space
    assert await repository.get_category(category.id) == category
    assert session.flushes == 2


@pytest.mark.asyncio
async def test_sqlalchemy_space_repository_persists_share_link_categories_separately_from_token_hash() -> None:
    session = FakeSession()
    repository = SqlAlchemySpaceRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    link = ShareLink(
        id=uuid4(),
        space_id=uuid4(),
        category_ids=(uuid4(), uuid4()),
        token_hash="a" * 64,
        status=ShareLinkStatus.ACTIVE,
        created_at=now,
    )

    await repository.add_share_link(link)

    persisted = session.added[0]
    assert persisted.token_hash == "a" * 64  # type: ignore[attr-defined]
    assert not hasattr(persisted, "token")
    _, rows = session.executed[0]
    assert rows == [
        {"share_link_id": link.id, "category_id": link.category_ids[0]},
        {"share_link_id": link.id, "category_id": link.category_ids[1]},
    ]
    assert session.events == ["add", "flush", "execute"]
    assert session.flushes == 1
