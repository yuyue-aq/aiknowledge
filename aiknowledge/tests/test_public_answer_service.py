from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.domain.public_answers import (
    PublicAnswer,
    PublicAnswerRuleViolationError,
    PublicAnswerSourceRef,
    PublicAnswerStatus,
    PublicContentMode,
)
from app.domain.users import SpaceRole
from app.services.public_answers import PublicAnswerService


class FakeEmbedding:
    def __init__(self):
        self.calls = []

    async def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3]]


class FakeRepository:
    def __init__(self):
        self.roles = {}
        self.answers = {}
        self.valid_for_publish = True
        self.published = []
        self.withdrawn = []
        self.updated = []

    async def get_space_role(self, *, space_id, user_id):
        return self.roles.get((space_id, user_id))

    async def get_public_answer(self, answer_id):
        return self.answers.get(answer_id)

    async def list_public_answers(self, space_id):
        return [item for item in self.answers.values() if item.space_id == space_id]

    async def add_public_answer(self, answer):
        self.answers[answer.id] = answer

    async def validate_public_answer_draft(self, _answer):
        return True

    async def update_public_answer(self, answer, *, revoke_published_reason=None):
        self.answers[answer.id] = answer
        self.updated.append((answer, revoke_published_reason))

    async def transition_public_answer(self, *, answer_id, expected_status, status, actor_id, at):
        current = self.answers[answer_id]
        if current.status not in expected_status:
            return None
        updated = replace(current, status=status, reviewed_by=actor_id if status == PublicAnswerStatus.APPROVED else current.reviewed_by,
                          reviewed_at=at if status == PublicAnswerStatus.APPROVED else current.reviewed_at,
                          updated_at=at)
        self.answers[answer_id] = updated
        return updated

    async def validate_public_answer(self, answer, *, at):
        return self.valid_for_publish

    async def publish_public_answer(self, *, answer_id, actor_id, embedding, at):
        current = self.answers[answer_id]
        version_id = uuid4()
        updated = replace(current, status=PublicAnswerStatus.PUBLISHED, published_version_id=version_id,
                          published_version_number=(current.published_version_number or 0) + 1,
                          updated_at=at, withdrawal_reason=None)
        self.answers[answer_id] = updated
        self.published.append((answer_id, actor_id, embedding, at))
        return updated

    async def withdraw_public_answer(self, *, answer_id, actor_id, reason, at):
        current = self.answers[answer_id]
        if current.status != PublicAnswerStatus.PUBLISHED:
            return None
        updated = replace(current, status=PublicAnswerStatus.WITHDRAWN, withdrawal_reason=reason,
                          updated_at=at)
        self.answers[answer_id] = updated
        self.withdrawn.append((answer_id, actor_id, reason, at))
        return updated


def setup_service():
    repository = FakeRepository()
    embedding = FakeEmbedding()
    now = datetime(2026, 10, 9, tzinfo=UTC)
    owner, admin, editor = uuid4(), uuid4(), uuid4()
    space_id, category_id = uuid4(), uuid4()
    repository.roles[(space_id, owner)] = SpaceRole.OWNER
    repository.roles[(space_id, admin)] = SpaceRole.ADMIN
    repository.roles[(space_id, editor)] = SpaceRole.EDITOR
    service = PublicAnswerService(repository=repository, embedding_client=embedding, clock=lambda: now)
    return service, repository, embedding, owner, admin, editor, space_id, category_id


@pytest.mark.asyncio
async def test_team_admin_can_draft_submit_and_review_but_only_owner_can_publish():
    service, repository, embedding, owner, admin, _editor, space_id, category_id = setup_service()

    draft = await service.create(
        space_id=space_id, actor_user_id=admin, category_id=category_id,
        question='如何申请报销？', answer='按制度提交单据。',
    )
    submitted = await service.submit_for_review(draft.id, actor_user_id=admin)
    approved = await service.approve(draft.id, actor_user_id=admin)

    with pytest.raises(PermissionError):
        await service.publish(draft.id, actor_user_id=admin)

    published = await service.publish(draft.id, actor_user_id=owner)
    assert submitted.status is PublicAnswerStatus.IN_REVIEW
    assert approved.status is PublicAnswerStatus.APPROVED
    assert published.status is PublicAnswerStatus.PUBLISHED
    assert published.published_version_number == 1
    assert embedding.calls == [['问题：如何申请报销？\n答案：按制度提交单据。']]
    assert repository.published[0][1:3] == (owner, [0.1, 0.2, 0.3])


@pytest.mark.asyncio
async def test_personal_owner_is_admin_and_can_manage_public_answer():
    service, _repository, _embedding, owner, _admin, _editor, space_id, category_id = setup_service()
    draft = await service.create(
        space_id=space_id, actor_user_id=owner, category_id=category_id,
        question='如何申请报销？', answer='按制度提交单据。',
    )
    assert draft.created_by == owner


@pytest.mark.asyncio
async def test_editor_cannot_read_or_mutate_public_answer_management():
    service, _repository, _embedding, _owner, _admin, editor, space_id, category_id = setup_service()
    with pytest.raises(PermissionError):
        await service.create(
            space_id=space_id, actor_user_id=editor, category_id=category_id,
            question='问题', answer='答案',
        )


@pytest.mark.asyncio
async def test_invalid_state_and_unavailable_source_block_publication():
    service, repository, embedding, owner, admin, _editor, space_id, category_id = setup_service()
    draft = await service.create(
        space_id=space_id, actor_user_id=admin, category_id=category_id,
        question='如何申请报销？', answer='按制度提交单据。',
        source_refs=(PublicAnswerSourceRef(uuid4(), uuid4()),),
    )
    with pytest.raises(PublicAnswerRuleViolationError):
        await service.publish(draft.id, actor_user_id=owner)
    await service.submit_for_review(draft.id, actor_user_id=admin)
    await service.approve(draft.id, actor_user_id=admin)
    repository.valid_for_publish = False
    with pytest.raises(PublicAnswerRuleViolationError):
        await service.publish(draft.id, actor_user_id=owner)
    assert embedding.calls == []
    assert repository.answers[draft.id].status is PublicAnswerStatus.APPROVED


@pytest.mark.asyncio
async def test_editing_a_published_answer_withdraws_the_old_snapshot_before_review():
    service, repository, _embedding, owner, admin, _editor, space_id, category_id = setup_service()
    draft = await service.create(
        space_id=space_id, actor_user_id=admin, category_id=category_id,
        question='问题', answer='旧答案',
    )
    await service.submit_for_review(draft.id, actor_user_id=admin)
    await service.approve(draft.id, actor_user_id=admin)
    published = await service.publish(draft.id, actor_user_id=owner)
    edited = await service.update(
        published.id, actor_user_id=admin, answer='新答案',
    )
    assert edited.status is PublicAnswerStatus.DRAFT
    assert edited.published_version_id is None
    assert repository.updated[-1][1] == 'CONTENT_CHANGED'


@pytest.mark.asyncio
async def test_share_link_content_mode_defaults_to_existing_document_behavior():
    assert PublicContentMode.DOCUMENTS.value == 'DOCUMENTS'
