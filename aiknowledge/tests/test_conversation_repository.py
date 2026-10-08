from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationKind,
    ConversationMessage,
    MessageRole,
    RagRun,
)
from app.domain.rag import AnswerStatus
from app.domain.spaces import PublicRetrievalScope
from app.infrastructure.database.conversation_repository import SqlAlchemyConversationRepository
from app.infrastructure.database.models import (
    CitationRecord,
    ConversationRecord,
    MessageRecord,
    RagRunRecord,
)


class FakeRows:
    def __init__(self, rows) -> None:  # type: ignore[no-untyped-def]
        self._rows = rows

    def all(self):  # type: ignore[no-untyped-def]
        return self._rows


class FakeSession:
    def __init__(self) -> None:
        self.records: dict[type, dict[object, object]] = {}
        self.added: list[object] = []
        self.executed: list[object] = []
        self.query_rows = []
        self.flushes = 0

    def add(self, record: object) -> None:
        self.added.append(record)
        self.records.setdefault(type(record), {})[record.id] = record  # type: ignore[attr-defined]

    async def get(self, model: type, record_id: object, **_: object) -> object | None:
        return self.records.get(model, {}).get(record_id)

    async def execute(self, statement: object):
        self.executed.append(statement)
        return FakeRows(self.query_rows)

    async def scalars(self, statement: object):
        self.executed.append(statement)
        return FakeRows(self.query_rows)

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.asyncio
async def test_public_page_heading_fallback_stays_in_same_authorized_version_and_category():
    session=FakeSession()
    session.query_rows=[SimpleNamespace(id=uuid4(),document_id=uuid4(),document_name='档案.pdf',
        content='指标为0.86。',page_number=2,ordinal=3,distance=.1,heading_path=[],
        page_prefix='02 项目经历：项目甲\n项目时间与角色\n开发者介绍')]
    scope=PublicRetrievalScope(share_link_id=uuid4(),space_id=uuid4(),category_ids=(uuid4(),))
    result=await SqlAlchemyConversationRepository(session).retrieve_public(scope=scope,embedding=[1.]*1024,limit=4)
    assert result[0].heading_path == ('02 项目经历：项目甲',)
    assert result[0].content == '指标为0.86。'
    sql=str(session.executed[0].compile(dialect=postgresql.dialect()))
    assert 'page_start.document_version_id = chunks.document_version_id' in sql
    assert 'page_start.category_id IS NOT DISTINCT FROM chunks.category_id' in sql
    assert 'page_start.is_active IS true' in sql
    assert 'categories.is_open IS true' in sql


@pytest.mark.asyncio
async def test_history_citations_mark_unavailable_sources_using_current_version_and_time():
    session = FakeSession()
    record = CitationRecord(id=uuid4(), message_id=uuid4(), chunk_id=None, document_name='已删除.txt',
        quoted_text='历史引用', page_number=None, ordinal=1, score=.9)
    session.query_rows = [(record, False)]
    citations = await SqlAlchemyConversationRepository(session).list_citations([record.message_id])
    assert citations[0].source_available is False
    sql = str(session.executed[0])
    assert 'active_version_id' in sql
    assert 'clock_timestamp()' in sql
    assert 'deleted_at IS NULL' in sql


@pytest.mark.asyncio
async def test_conversation_repository_persists_conversation_messages_and_citation_snapshots() -> None:
    session = FakeSession()
    repository = SqlAlchemyConversationRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    conversation = Conversation(
        id=uuid4(),
        space_id=uuid4(),
        kind=ConversationKind.OWNER,
        share_link_id=None,
        title=None,
        created_at=now,
        updated_at=now,
    )
    message = ConversationMessage(
        id=uuid4(),
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="可追溯回答",
        answer_status=AnswerStatus.ANSWERED,
        model="deepseek-v4-flash",
        prompt_tokens=12,
        completion_tokens=5,
        created_at=now,
    )
    citation = CitationSnapshot(
        id=uuid4(),
        message_id=message.id,
        chunk_id=uuid4(),
        document_name="制度说明.pdf",
        quoted_text="资料片段",
        page_number=2,
        ordinal=4,
        score=0.91,
    )
    rag_run = RagRun(
        id=uuid4(),
        trace_id=uuid4(),
        message_id=message.id,
        prompt_version="rag-prompt-v1",
        rewritten_question="可追溯回答依据？",
        model_snapshot={"chat_model": "deepseek-v4-flash"},
        retrieval_config_snapshot={"candidate_limit": 12, "top_k": 4},
        retrieved_chunk_ids=(citation.chunk_id,),
        selected_chunk_ids=(citation.chunk_id,),
        input_tokens=12,
        output_tokens=5,
        first_token_latency_ms=None,
        total_latency_ms=42,
        estimated_cost=None,
        created_at=now,
    )

    await repository.add_conversation(conversation)
    await repository.add_message(message)
    await repository.add_citations((citation,))
    await repository.add_rag_run(rag_run)

    assert isinstance(session.added[0], ConversationRecord)
    assert isinstance(session.added[1], MessageRecord)
    assert session.added[1].answer_status is AnswerStatus.ANSWERED  # type: ignore[attr-defined]
    assert isinstance(session.added[2], CitationRecord)
    assert session.added[2].quoted_text == "资料片段"  # type: ignore[attr-defined]
    assert isinstance(session.added[3], RagRunRecord)
    assert session.added[3].retrieved_chunk_ids == [str(citation.chunk_id)]  # type: ignore[attr-defined]
    assert await repository.get_conversation(conversation.id) == conversation
    assert session.flushes == 4


@pytest.mark.asyncio
async def test_retrieval_queries_apply_document_and_public_scope_filters_before_vector_ordering() -> None:
    session = FakeSession()
    repository = SqlAlchemyConversationRepository(session)  # type: ignore[arg-type]
    chunk_id = uuid4()
    session.query_rows = [
        SimpleNamespace(
            id=chunk_id,
            document_id=uuid4(),
            document_name="可见资料.txt",
            content="允许公开的内容。",
            page_number=None,
            ordinal=1,
            distance=0.08,
        )
    ]
    space_id = uuid4()
    scope = PublicRetrievalScope(
        share_link_id=uuid4(), space_id=space_id, category_ids=(uuid4(), uuid4())
    )

    owner_hits = await repository.retrieve_owner(
        space_id=space_id, embedding=[1.0, 0.0, 0.0], limit=12
    )
    public_hits = await repository.retrieve_public(
        scope=scope, embedding=[1.0, 0.0, 0.0], limit=12
    )

    assert owner_hits[0].id == chunk_id
    assert owner_hits[0].score == pytest.approx(0.92)
    assert public_hits[0].document_name == "可见资料.txt"
    owner_sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    public_sql = str(
        session.executed[1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    normalized_owner = owner_sql.lower()
    normalized_public = public_sql.lower()
    assert "chunks.is_active is true" in normalized_owner
    assert "documents.status" in normalized_owner
    assert "documents.active_version_id = chunks.document_version_id" in normalized_owner
    assert "documents.deleted_at is null" in normalized_owner
    assert "knowledge_spaces.deleted_at is null" in normalized_owner
    assert "chunks.embedding <=>" in normalized_owner
    assert "order by distance" in normalized_owner
    assert "categories.is_open is true" in normalized_public
    assert "categories.deleted_at is null" in normalized_public
    assert "knowledge_spaces.visibility" in normalized_public
    assert "chunks.category_id in" in normalized_public


@pytest.mark.asyncio
async def test_conversation_list_query_is_owner_only_and_recent_first() -> None:
    session = FakeSession()
    repository = SqlAlchemyConversationRepository(session)  # type: ignore[arg-type]
    now = datetime(2026, 9, 11, tzinfo=UTC)
    space_id = uuid4()
    conversation = ConversationRecord(
        id=uuid4(),
        space_id=space_id,
        kind=ConversationKind.OWNER,
        share_link_id=None,
        title="最近对话",
        created_at=now,
        updated_at=now,
    )
    session.query_rows = [conversation]

    result = await repository.list_conversations(space_id)

    assert result[0].id == conversation.id
    sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()
    assert "conversations.space_id" in sql
    assert "conversations.kind = 'owner'" in sql
    assert "knowledge_spaces.deleted_at is null" in sql
    assert "order by conversations.updated_at desc" in sql


@pytest.mark.asyncio
async def test_public_keyword_corpus_filters_scope_before_bm25_statistics():
    session=FakeSession();repo=SqlAlchemyConversationRepository(session)
    sid,cid=uuid4(),uuid4()
    scope=PublicRetrievalScope(share_link_id=uuid4(),space_id=sid,category_ids=(cid,))
    await repo.keyword_corpus(space_id=sid,public_scope=scope,limit=5001)
    sql=str(session.executed[-1].compile(dialect=postgresql.dialect(),compile_kwargs={'literal_binds':True}))
    for value in [str(sid),str(cid),'is_open IS true','is_enabled IS true','active_version_id','expires_at','deleted_at IS NULL','is_active IS true']:
        assert value in sql
    assert 'LIMIT 5001' in sql
    session.executed.clear()
    assert await repo.keyword_corpus(space_id=uuid4(),public_scope=scope,limit=5001)==[]
    assert not session.executed
