from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies import get_current_user, get_database_session
from app.core.config import Settings
from app.domain.public_answers import PublicAnswer, PublicAnswerSourceRef, PublicAnswerStatus
from app.main import create_app


class PublicAnswerServiceStub:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.space_id = uuid4()
        self.category_id = uuid4()
        self.document_id = uuid4()
        self.document_version_id = uuid4()
        self.calls: list[dict[str, object]] = []

    def answer(self, *, status: PublicAnswerStatus = PublicAnswerStatus.DRAFT) -> PublicAnswer:
        now = datetime(2026, 10, 9, tzinfo=UTC)
        return PublicAnswer(
            id=uuid4(), space_id=self.space_id, category_id=self.category_id,
            question='如何申请？', answer='提交申请表。', status=status,
            source_refs=(PublicAnswerSourceRef(self.document_id, self.document_version_id),),
            created_by=self.user_id, updated_by=self.user_id, created_at=now, updated_at=now,
        )

    async def list(self, space_id, **kwargs):
        self.calls.append({'method': 'list', 'space_id': space_id, **kwargs})
        return [self.answer()]

    async def create(self, **kwargs):
        self.calls.append({'method': 'create', **kwargs})
        return self.answer()

    async def update(self, answer_id, **kwargs):
        self.calls.append({'method': 'update', 'answer_id': answer_id, **kwargs})
        return self.answer()

    async def submit_for_review(self, answer_id, **kwargs):
        self.calls.append({'method': 'submit', 'answer_id': answer_id, **kwargs})
        return self.answer(status=PublicAnswerStatus.IN_REVIEW)

    async def approve(self, answer_id, **kwargs):
        self.calls.append({'method': 'approve', 'answer_id': answer_id, **kwargs})
        return self.answer(status=PublicAnswerStatus.APPROVED)

    async def publish(self, answer_id, **kwargs):
        self.calls.append({'method': 'publish', 'answer_id': answer_id, **kwargs})
        return self.answer(status=PublicAnswerStatus.PUBLISHED)

    async def withdraw(self, answer_id, **kwargs):
        self.calls.append({'method': 'withdraw', 'answer_id': answer_id, **kwargs})
        return self.answer(status=PublicAnswerStatus.WITHDRAWN)


def app_for(service: PublicAnswerServiceStub, *, authenticated: bool = True):
    app = create_app(
        settings=Settings(auth_required=False),
        public_answer_service_factory=lambda _session: service,
    )

    async def session():
        yield None

    app.dependency_overrides[get_database_session] = session
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=service.user_id)
    return app


@pytest.mark.asyncio
async def test_public_answer_management_routes_map_source_refs_and_auth_actor():
    service = PublicAnswerServiceStub()
    app = app_for(service)
    payload = {
        'category_id': str(service.category_id),
        'question': '如何申请？',
        'answer': '提交申请表。',
        'source_refs': [{
            'document_id': str(service.document_id),
            'document_version_id': str(service.document_version_id),
        }],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        created = await client.post(f'/api/v1/spaces/{service.space_id}/public-answers', json=payload)
        listed = await client.get(f'/api/v1/spaces/{service.space_id}/public-answers')

    assert created.status_code == 201
    assert created.json()['source_refs'] == payload['source_refs']
    assert listed.status_code == 200
    assert listed.json()['items'][0]['question'] == '如何申请？'
    assert service.calls[0]['actor_user_id'] == service.user_id
    assert service.calls[0]['source_refs'] == [PublicAnswerSourceRef(service.document_id, service.document_version_id)]


@pytest.mark.asyncio
async def test_public_answer_management_requires_authenticated_user():
    service = PublicAnswerServiceStub()
    app = app_for(service, authenticated=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(f'/api/v1/spaces/{service.space_id}/public-answers')
    assert response.status_code == 401
    assert service.calls == []
