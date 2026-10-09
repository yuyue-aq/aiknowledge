from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationAnswer,
    ConversationDetail,
    ConversationKind,
    ConversationMessage,
    MessageRole,
)
from app.domain.rag import AnswerStatus
from app.domain.spaces import Category, KnowledgeSpace, PublicRetrievalScope, SpaceVisibility
from app.domain.public_answers import PublicContentMode
from app.api.dependencies import get_database_session
from app.core.config import Settings
from app.main import create_app
from app.api.v1.conversations import OwnerAnswerResponse, OwnerConversationDetailResponse, PublicAnswerResponse, _as_sse, get_public_scope


@pytest.mark.asyncio
async def test_public_hybrid_strategy_goes_to_generation_not_question_quota():
    spaces=FakePublicSpaceService()
    conversations=FakeConversationService(spaces.space.id,spaces.link_id)
    strategies=[]
    async def ask(**kwargs):
        strategies.append(kwargs['strategy'])
        return conversations._answer(kwargs['conversation_id'],kwargs['question'])
    conversations.ask_public=ask
    app=create_app(settings=Settings(auth_required=False),conversation_service_factory=lambda _:conversations,
        space_service_factory=lambda _:spaces,
        public_question_limit_service_factory=lambda _:FakePublicQuestionLimitService())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        await client.post('/api/v1/public/session',json={'token':'only-returned-once-token'})
        response=await client.post(f'/api/v1/public/conversations/{conversations.public_conversation_id}/messages',json={'question':'开放规则？','strategy':'hybrid'})
    assert response.status_code==200 and strategies==['hybrid']
    assert set(response.json())=={'message_id','status','answer','sources'}
    assert response.json()['sources'] == []


def test_public_answer_response_only_exposes_curated_public_answer_sources():
    now = datetime.now(UTC)
    conversation_id, user_id, assistant_id = uuid4(), uuid4(), uuid4()
    user = ConversationMessage(user_id, conversation_id, MessageRole.USER, '问题', now)
    assistant = ConversationMessage(
        assistant_id, conversation_id, MessageRole.ASSISTANT, '答案', now,
        answer_status=AnswerStatus.ANSWERED,
    )
    curated_version_id = uuid4()
    answer = ConversationAnswer(
        user=user,
        assistant=assistant,
        citations=(
            CitationSnapshot(uuid4(), assistant_id, uuid4(), '私有文档.pdf', '私有原文', 1, 1, 0.2),
            CitationSnapshot(uuid4(), assistant_id, None, '审核问题', '审核答案', None, 1, 0.1,
                public_answer_version_id=curated_version_id),
        ),
    )

    response = PublicAnswerResponse.from_domain(answer)

    assert [source.model_dump() for source in response.sources] == [
        {'title': '审核问题', 'content': '审核答案'},
    ]


@pytest.mark.asyncio
async def test_public_space_only_returns_share_scoped_published_faq_questions():
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    faq_calls = []

    async def list_faq(*, scope, limit):
        faq_calls.append({'scope': scope, 'limit': limit})
        return ['如何申请？', '何时到账？']

    conversations.list_public_faq_questions = list_faq
    app = create_app(
        settings=Settings(auth_required=False),
        conversation_service_factory=lambda _: conversations,
        space_service_factory=lambda _: spaces,
    )
    async def session():
        yield None
    app.dependency_overrides[get_database_session] = session
    curated_scope = replace(spaces.scope, content_mode=PublicContentMode.PUBLISHED_ANSWERS)
    app.dependency_overrides[get_public_scope] = lambda: curated_scope

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        curated = await client.get('/api/v1/public/space')
        app.dependency_overrides[get_public_scope] = lambda: spaces.scope
        documents = await client.get('/api/v1/public/space')

    assert curated.status_code == 200
    assert curated.json()['content_mode'] == 'PUBLISHED_ANSWERS'
    assert curated.json()['suggested_questions'] == ['如何申请？', '何时到账？']
    assert 'answer' not in curated.json()
    assert faq_calls == [{'scope': curated_scope, 'limit': 6}]
    assert documents.json()['content_mode'] == 'DOCUMENTS'
    assert documents.json()['suggested_questions'] == []


@pytest.mark.asyncio
async def test_sse_stops_output_when_access_is_revoked_mid_stream():
    from types import SimpleNamespace
    checks = 0
    async def disconnected():
        return False
    async def check():
        nonlocal checks
        checks += 1
        return checks == 1
    payload = OwnerAnswerResponse.model_construct(answer='证据回答' * 30)
    response = _as_sse(payload, SimpleNamespace(is_disconnected=disconnected), scope_check=check)
    events = [event async for event in response.body_iterator]
    assert len([x for x in events if x.startswith('event: delta')]) == 1
    assert any('SCOPE_CHANGED' in x for x in events)
    assert not any(x.startswith('event: answer') or x.startswith('event: done') for x in events)


class FakeConversationService:
    def __init__(self, space_id: UUID, share_link_id: UUID) -> None:
        self.space_id = space_id
        self.share_link_id = share_link_id
        self.owner_conversation_id = uuid4()
        self.public_conversation_id = uuid4()
        self.public_scopes = []
        self.metadata_filters = []
        self.deleted = []
        self.now = datetime(2026, 9, 11, tzinfo=UTC)

    async def create_owner_conversation(self, *, space_id: UUID, title: str | None = None):
        return Conversation(
            id=self.owner_conversation_id,
            space_id=space_id,
            kind=ConversationKind.OWNER,
            share_link_id=None,
            title=title,
            created_at=self.now,
            updated_at=self.now,
        )

    async def create_public_conversation(self, *, scope: PublicRetrievalScope, title: str | None = None):
        self.public_scopes.append(scope)
        return Conversation(
            id=self.public_conversation_id,
            space_id=scope.space_id,
            kind=ConversationKind.PUBLIC,
            share_link_id=scope.share_link_id,
            title=title,
            created_at=self.now,
            updated_at=self.now,
        )

    async def ask_owner(self, *, conversation_id: UUID, question: str, metadata_filter=None) -> ConversationAnswer:
        self.metadata_filters.append(metadata_filter)
        return self._answer(conversation_id, question)

    async def ask_public(
        self, *, conversation_id: UUID, scope: PublicRetrievalScope, question: str, metadata_filter=None
    ) -> ConversationAnswer:
        self.public_scopes.append(scope)
        self.metadata_filters.append(metadata_filter)
        return self._answer(conversation_id, question)

    async def get_owner_conversation(self, conversation_id: UUID) -> ConversationDetail:
        conversation = await self.create_owner_conversation(space_id=self.space_id)
        answer = self._answer(conversation_id, "历史问题")
        return ConversationDetail(
            conversation=conversation,
            messages=(answer.user, answer.assistant),
            citations_by_message={answer.assistant.id: answer.citations},
        )

    async def list_owner_conversations(self, space_id: UUID) -> tuple[Conversation, ...]:
        return (
            Conversation(
                id=self.owner_conversation_id,
                space_id=space_id,
                kind=ConversationKind.OWNER,
                share_link_id=None,
                title="最近对话",
                created_at=self.now,
                updated_at=self.now,
            ),
        )

    async def delete_owner_conversation(self, conversation_id: UUID) -> None:
        self.deleted.append(conversation_id)

    def _answer(self, conversation_id: UUID, question: str) -> ConversationAnswer:
        user = ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            content=question,
            created_at=self.now,
        )
        assistant = ConversationMessage(
            id=uuid4(),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content="开放分类可以提供归纳回答。",
            answer_status=AnswerStatus.ANSWERED,
            model="deepseek-v4-flash",
            created_at=self.now,
        )
        citation = CitationSnapshot(
            id=uuid4(),
            message_id=assistant.id,
            chunk_id=uuid4(),
            document_name="私有文件名不能出现在访客响应.pdf",
            quoted_text="私有引用片段不能出现在访客响应。",
            page_number=7,
            ordinal=3,
            score=0.92,
        )
        return ConversationAnswer(user=user, assistant=assistant, citations=(citation,))


class FakePublicSpaceService:
    def __init__(self) -> None:
        now = datetime(2026, 9, 11, tzinfo=UTC)
        self.space = KnowledgeSpace(
            id=uuid4(),
            name="产品公开知识库",
            description="仅开放的产品说明",
            visibility=SpaceVisibility.PUBLIC,
            guest_feedback_enabled=False,
            created_at=now,
            updated_at=now,
        )
        self.category = Category(
            id=uuid4(),
            space_id=self.space.id,
            name="产品说明",
            description="访客可问",
            is_open=True,
            sort_order=0,
            created_at=now,
            updated_at=now,
        )
        self.link_id = uuid4()
        self.scope = PublicRetrievalScope(
            share_link_id=self.link_id,
            space_id=self.space.id,
            category_ids=(self.category.id,),
        )

    async def resolve_public_scope(self, raw_token: str) -> PublicRetrievalScope:
        assert raw_token == "only-returned-once-token"
        return self.scope

    async def resolve_public_scope_by_link_id(self, link_id: UUID) -> PublicRetrievalScope:
        assert link_id == self.link_id
        return self.scope

    async def get_space(self, space_id: UUID) -> KnowledgeSpace:
        assert space_id == self.space.id
        return self.space

    async def list_categories(self, space_id: UUID) -> list[Category]:
        assert space_id == self.space.id
        return [self.category]


class FakePublicQuestionLimitService:
    async def check_and_record(self, **_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_owner_api_returns_source_citations_but_public_api_never_serializes_them() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
        public_question_limit_service_factory=lambda _: FakePublicQuestionLimitService(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner_created = await client.post(
            "/api/v1/owner/conversations", json={"space_id": str(spaces.space.id)}
        )
        owner_answer = await client.post(
            f"/api/v1/owner/conversations/{conversations.owner_conversation_id}/messages",
            json={"question": "访客可以访问什么？", "stream": False,
                  "metadata_filter": {"formats": ["pdf"], "version_min": 2}},
        )
        session = await client.post(
            "/api/v1/public/session", json={"token": "only-returned-once-token"}
        )
        public_space = await client.get("/api/v1/public/space")
        public_created = await client.post("/api/v1/public/conversations", json={})
        public_answer = await client.post(
            f"/api/v1/public/conversations/{conversations.public_conversation_id}/messages",
            json={"question": "访客可以访问什么？", "stream": False,
                  "metadata_filter": {"formats": ["markdown"]}},
        )

    assert owner_created.status_code == 201
    assert owner_answer.status_code == 200
    assert owner_answer.json()["citations"][0]["document_name"] == "私有文件名不能出现在访客响应.pdf"
    assert session.status_code == 200
    assert "only-returned-once-token" not in session.headers["set-cookie"]
    assert "httponly" in session.headers["set-cookie"].lower()
    assert public_space.json()["name"] == "产品公开知识库"
    assert public_created.status_code == 201
    assert public_answer.status_code == 200
    assert conversations.metadata_filters[0].formats == ("pdf",)
    assert conversations.metadata_filters[-1].formats == ("markdown",)
    serialized_public_answer = public_answer.text
    assert '"citations"' not in serialized_public_answer
    assert "document_name" not in serialized_public_answer
    assert "quoted_text" not in serialized_public_answer
    assert "私有文件名不能出现在访客响应.pdf" not in serialized_public_answer
    assert "私有引用片段不能出现在访客响应。" not in serialized_public_answer
    assert conversations.public_scopes == [spaces.scope, spaces.scope]


@pytest.mark.asyncio
async def test_public_query_endpoint_accepts_share_token_without_browser_cookie() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    category_id = uuid4()

    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
        public_question_limit_service_factory=lambda _: FakePublicQuestionLimitService(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/public/query",
            json={"token": "only-returned-once-token", "question": "公开入口能回答什么？",
                  "metadata_filter": {"category_ids": [str(category_id)], "formats": ["pdf"]}},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ANSWERED"
    assert "citations" not in response.json()
    assert "only-returned-once-token" not in response.text
    assert conversations.metadata_filters[-1].category_ids == (category_id,)
    assert conversations.metadata_filters[-1].formats == ("pdf",)


@pytest.mark.asyncio
async def test_public_share_origin_allowlist_rejects_untrusted_browser_origins() -> None:
    spaces = FakePublicSpaceService()
    spaces.scope = replace(spaces.scope, allowed_origins=("https://trusted.example",))
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        settings=Settings(cors_allowed_origins="https://evil.example,https://trusted.example"),
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        blocked = await client.post(
            "/api/v1/public/session",
            json={"token": "only-returned-once-token"},
            headers={"Origin": "https://evil.example"},
        )
        allowed = await client.post(
            "/api/v1/public/session",
            json={"token": "only-returned-once-token"},
            headers={"Origin": "https://trusted.example/"},
        )
        direct_blocked = await client.post(
            "/api/v1/public/query",
            json={"token": "only-returned-once-token", "question": "测试"},
            headers={"Origin": "https://evil.example"},
        )

    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PUBLIC_ACCESS_DENIED"
    assert allowed.status_code == 200
    assert direct_blocked.status_code == 403


@pytest.mark.asyncio
async def test_owner_history_keeps_citations_and_owner_can_delete_a_conversation() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        history = await client.get(
            f"/api/v1/owner/conversations/{conversations.owner_conversation_id}"
        )
        deleted = await client.delete(
            f"/api/v1/owner/conversations/{conversations.owner_conversation_id}"
        )

    assert history.status_code == 200
    assert history.json()["messages"][1]["citations"][0]["quoted_text"] == "私有引用片段不能出现在访客响应。"
    assert deleted.status_code == 204
    assert conversations.deleted == [conversations.owner_conversation_id]


@pytest.mark.asyncio
async def test_owner_conversation_list_returns_only_the_requested_space() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get(
            "/api/v1/owner/conversations",
            params={"space_id": str(spaces.space.id)},
        )

    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "最近对话"
    assert listed.json()[0]["space_id"] == str(spaces.space.id)


@pytest.mark.asyncio
async def test_streaming_owner_answer_emits_incremental_delta_then_final_answer() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        streamed = await client.post(
            f"/api/v1/owner/conversations/{conversations.owner_conversation_id}/messages",
            json={"question": "请流式回答", "stream": True},
        )

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in streamed.text
    assert '"text": "开放分类可以提供归纳回答。"' in streamed.text
    assert "event: answer" in streamed.text
    assert "event: done" in streamed.text


@pytest.mark.asyncio
async def test_streaming_public_answer_keeps_source_fields_out_of_every_event() -> None:
    spaces = FakePublicSpaceService()
    conversations = FakeConversationService(spaces.space.id, spaces.link_id)
    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
        public_question_limit_service_factory=lambda _: FakePublicQuestionLimitService(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.post("/api/v1/public/session", json={"token": "only-returned-once-token"})
        streamed = await client.post(
            f"/api/v1/public/conversations/{conversations.public_conversation_id}/messages",
            json={"question": "请流式回答", "stream": True},
        )

    assert streamed.status_code == 200
    assert "event: delta" in streamed.text
    assert "event: answer" in streamed.text
    assert '"citations"' not in streamed.text
    assert "私有文件名不能出现在访客响应.pdf" not in streamed.text


@pytest.mark.asyncio
async def test_sse_generator_stops_before_final_events_when_client_disconnects() -> None:
    class DisconnectingRequest:
        calls = 0

        async def is_disconnected(self) -> bool:
            self.calls += 1
            return self.calls >= 2

    payload = OwnerAnswerResponse(
        message_id=uuid4(),
        status=AnswerStatus.ANSWERED,
        answer="一段足够长的回答，用于验证断开后的事件不会继续发送。",
        model="deepseek-v4-flash",
        citations=[],
    )
    response = _as_sse(payload, DisconnectingRequest())

    chunks = [chunk async for chunk in response.body_iterator]
    body = b"".join(
        chunk if isinstance(chunk, bytes) else chunk.encode("utf-8") for chunk in chunks
    ).decode("utf-8")

    assert "event: delta" in body
    assert "event: answer" not in body
    assert "event: done" not in body


def test_query_diagnostics_are_serialized_for_owners_and_omitted_from_public_response() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    user = ConversationMessage(
        id=uuid4(), conversation_id=uuid4(), role=MessageRole.USER,
        content='原问题', created_at=now,
    )
    assistant = ConversationMessage(
        id=uuid4(), conversation_id=user.conversation_id, role=MessageRole.ASSISTANT,
        content='有依据的回答', answer_status=AnswerStatus.ANSWERED,
        model='deepseek-v4-flash', created_at=now,
    )
    diagnostic = {
        'original_question': '原问题',
        'retrieval_question': '改写后的检索问题',
        'was_rewritten': True,
        'queries': [{
            'kind': 'primary', 'query': '改写后的检索问题', 'evidence': [{
                'chunk_id': str(uuid4()), 'document_name': '内部资料.txt',
                'ordinal': 3, 'rank': 1, 'score': .91,
                'score_kind': 'cosine', 'selected_for_context': True,
            }],
        }],
    }
    answer = ConversationAnswer(
        user=user, assistant=assistant, citations=(), query_diagnostics=diagnostic,
    )

    owner_payload = OwnerAnswerResponse.from_domain(answer).model_dump(mode='json')
    public_payload = PublicAnswerResponse.from_domain(answer).model_dump(mode='json')

    assert owner_payload['query_diagnostics']['original_question'] == '原问题'
    assert owner_payload['query_diagnostics']['queries'][0]['evidence'][0]['document_name'] == '内部资料.txt'
    assert 'query_diagnostics' not in public_payload
    assert '内部资料.txt' not in str(public_payload)

    conversation = Conversation(
        id=user.conversation_id, space_id=uuid4(), kind=ConversationKind.OWNER,
        share_link_id=None, title='检索诊断', created_at=now, updated_at=now,
    )
    detail = ConversationDetail(
        conversation=conversation, messages=(user, assistant), citations_by_message={},
        query_diagnostics_by_message={assistant.id: diagnostic},
    )
    history_payload = OwnerConversationDetailResponse.from_domain(detail).model_dump(mode='json')
    assert history_payload['messages'][1]['query_diagnostics']['original_question'] == '原问题'
