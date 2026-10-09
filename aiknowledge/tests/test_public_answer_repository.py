from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.public_answers import PublicAnswerStatus
from app.infrastructure.database.models import PublicAnswerRecord, PublicAnswerVersionRecord
from app.infrastructure.database.public_answer_repository import SqlAlchemyPublicAnswerRepository


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class SessionStub:
    def __init__(self, scalar_values, locked_document_ids=()):
        self.scalar_values = list(scalar_values)
        self.locked_document_ids = list(locked_document_ids)
        self.scalar_statements = []
        self.lock_statement = None
        self.added = []
        self.executed = []
        self.flushes = 0

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_values.pop(0)

    async def scalars(self, statement):
        self.lock_statement = statement
        return ScalarRows(self.locked_document_ids)

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        self.flushes += 1


def draft_record(space_id, category_id, source_id, source_version_id):
    now = datetime(2026, 10, 9, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid4(), space_id=space_id, category_id=category_id,
        question='如何申请？', answer='提交表单。', status='APPROVED',
        source_refs=[{'document_id': str(source_id), 'document_version_id': str(source_version_id)}],
        created_by=uuid4(), updated_by=uuid4(), reviewed_by=uuid4(), reviewed_at=now,
        created_at=now, updated_at=now, withdrawal_reason=None,
    )


@pytest.mark.asyncio
async def test_publish_locks_source_rows_and_revalidates_before_writing_snapshot():
    space_id, category_id, document_id, version_id, actor_id = (uuid4() for _ in range(5))
    record = draft_record(space_id, category_id, document_id, version_id)
    session = SessionStub(
        [record, record, None, object(), version_id, None],
        locked_document_ids=[document_id],
    )
    repository = SqlAlchemyPublicAnswerRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 10, 9, tzinfo=UTC)

    result = await repository.publish_public_answer(
        answer_id=record.id, actor_id=actor_id, embedding=[0.1, 0.2], at=now,
    )

    assert result is not None
    assert result.status is PublicAnswerStatus.PUBLISHED
    assert result.source_refs[0].document_version_id == version_id
    assert session.lock_statement._for_update_arg is not None
    assert session.scalar_statements[1]._for_update_arg is not None
    version = next(item for item in session.added if isinstance(item, PublicAnswerVersionRecord))
    assert version.status == 'PUBLISHED'
    assert version.source_count == 1
    assert version.embedding == [0.1, 0.2]
    assert record.status == 'PUBLISHED'


@pytest.mark.asyncio
async def test_publish_refuses_when_source_is_not_current_after_embedding():
    space_id, category_id, document_id, version_id, actor_id = (uuid4() for _ in range(5))
    record = draft_record(space_id, category_id, document_id, version_id)
    session = SessionStub(
        [record, record, None, object(), None],
        locked_document_ids=[document_id],
    )
    repository = SqlAlchemyPublicAnswerRepository(session)  # type: ignore[arg-type]

    result = await repository.publish_public_answer(
        answer_id=record.id, actor_id=actor_id, embedding=[0.1], at=datetime.now(UTC),
    )

    assert result is None
    assert not session.added
    assert record.status == 'APPROVED'
    assert not session.executed


@pytest.mark.asyncio
async def test_publish_refuses_if_source_document_disappeared_before_row_lock():
    space_id, category_id, document_id, version_id, actor_id = (uuid4() for _ in range(5))
    record = draft_record(space_id, category_id, document_id, version_id)
    session = SessionStub([record], locked_document_ids=[])
    repository = SqlAlchemyPublicAnswerRepository(session)  # type: ignore[arg-type]

    result = await repository.publish_public_answer(
        answer_id=record.id, actor_id=actor_id, embedding=[0.1], at=datetime.now(UTC),
    )

    assert result is None
    assert not session.added
    assert len(session.scalar_statements) == 1
