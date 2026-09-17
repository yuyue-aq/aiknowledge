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
from app.core.config import Settings
from app.main import create_app
from app.api.v1.conversations import OwnerAnswerResponse, _as_sse


class FakeConversationService:
    def __init__(self, space_id: UUID, share_link_id: UUID) -> None:
        self.space_id = space_id
        self.share_link_id = share_link_id
        self.owner_conversation_id = uuid4()
        self.public_conversation_id = uuid4()
        self.public_scopes = []
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

    async def ask_owner(self, *, conversation_id: UUID, question: str) -> ConversationAnswer:
        return self._answer(conversation_id, question)

    async def ask_public(
        self, *, conversation_id: UUID, scope: PublicRetrievalScope, question: str
    ) -> ConversationAnswer:
        self.public_scopes.append(scope)
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


@pytest.mark.asyncio
async def test_owner_api_returns_source_citations_but_public_api_never_serializes_them() -> None:
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
        owner_created = await client.post(
            "/api/v1/owner/conversations", json={"space_id": str(spaces.space.id)}
        )
        owner_answer = await client.post(
            f"/api/v1/owner/conversations/{conversations.owner_conversation_id}/messages",
            json={"question": "访客可以访问什么？", "stream": False},
        )
        session = await client.post(
            "/api/v1/public/session", json={"token": "only-returned-once-token"}
        )
        public_space = await client.get("/api/v1/public/space")
        public_created = await client.post("/api/v1/public/conversations", json={})
        public_answer = await client.post(
            f"/api/v1/public/conversations/{conversations.public_conversation_id}/messages",
            json={"question": "访客可以访问什么？", "stream": False},
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

    class FakeLimit:
        async def check_and_record(self, **_: object) -> None:
            return None

    app = create_app(
        rag_service=object(),
        space_service_factory=lambda _: spaces,
        conversation_service_factory=lambda _: conversations,
    )
    app.state.public_question_limit_service_factory = lambda _: FakeLimit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/public/query",
            json={"token": "only-returned-once-token", "question": "公开入口能回答什么？"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ANSWERED"
    assert "citations" not in response.json()
    assert "only-returned-once-token" not in response.text


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
