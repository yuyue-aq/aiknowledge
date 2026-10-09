from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.infrastructure.database.evaluation_repository import SqlAlchemyEvaluationRepository


class _Rows:
    def all(self):
        return []


class _ScalarRows:
    def all(self):
        return []

    def first(self):
        return None


class _Session:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows()

    async def scalars(self, statement):
        self.statements.append(statement)
        return _ScalarRows()

    async def scalar(self, statement):
        self.statements.append(statement)
        return 0


@pytest.mark.asyncio
async def test_knowledge_impact_repository_builds_postgres_queries_and_empty_report():
    session = _Session()
    repository = SqlAlchemyEvaluationRepository(session)

    report = await repository.get_knowledge_impact(uuid4())

    assert report['stale_case_count'] == 0
    assert report['updated_citation_count'] == 0
    assert report['answer_classification'] is None
    assert len(session.statements) == 5
    for statement in session.statements:
        assert str(statement.compile(dialect=postgresql.dialect()))
