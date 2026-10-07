from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies import get_current_user, get_database_session
from app.core.config import Settings
from app.domain.conversations import EvalRun, EvalRunStatus
from app.main import create_app


class Service:
    def __init__(self):
        self.user_id, self.space_id, self.version_id = uuid4(), uuid4(), uuid4()
        self.calls = []
        self.run = EvalRun(uuid4(), self.space_id, EvalRunStatus.PENDING, {'schema_version': 2},
            datetime.now(UTC), progress_total=50, task_id='task-test')

    async def enqueue_run(self, **kwargs):
        self.calls.append(kwargs)
        return self.run

    async def redispatch_run(self, run_id, **kwargs):
        self.calls.append({'run_id': run_id, **kwargs})
        return self.run


def app_for(service, auth=True):
    app = create_app(settings=Settings(auth_required=False), evaluation_service_factory=lambda session: service)
    async def session():
        yield None
    app.dependency_overrides[get_database_session] = session
    if auth:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=service.user_id)
    return app


@pytest.mark.asyncio
async def test_async_endpoints_return_202_and_durable_progress_without_waiting_for_llm():
    service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service)), base_url='http://test') as client:
        first = await client.post(f'/api/v1/spaces/{service.space_id}/eval-runs/async')
        version = await client.post(f'/api/v1/eval-versions/{service.version_id}/runs/async')
        retry = await client.post(f'/api/v1/eval-runs/{service.run.id}/retry')
    for response in (first, version, retry):
        assert response.status_code == 202
        assert response.json()['status'] == 'PENDING'
        assert response.json()['progress_total'] == 50
        assert response.json()['progress_completed'] == 0
        assert response.json()['id'] == str(service.run.id)
    assert service.calls[0]['owner_user_id'] == service.user_id
    assert service.calls[1]['version_id'] == service.version_id


@pytest.mark.asyncio
async def test_async_endpoint_requires_auth_even_when_legacy_auth_is_optional():
    service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(service, False)), base_url='http://test') as client:
        response = await client.post(f'/api/v1/spaces/{service.space_id}/eval-runs/async')
    assert response.status_code == 401
    assert not service.calls
