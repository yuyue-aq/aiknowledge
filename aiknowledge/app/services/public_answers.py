from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.public_answers import (
    PublicAnswer,
    PublicAnswerNotFoundError,
    PublicAnswerRuleViolationError,
    PublicAnswerSourceRef,
    PublicAnswerStatus,
)
from app.domain.spaces import SpaceAccessDeniedError
from app.domain.users import SpaceRole


class PublicAnswerRepository(Protocol):
    async def get_space_role(self, *, space_id: UUID, user_id: UUID) -> SpaceRole | None: ...

    async def get_public_answer(self, answer_id: UUID) -> PublicAnswer | None: ...

    async def list_public_answers(self, space_id: UUID) -> list[PublicAnswer]: ...

    async def add_public_answer(self, answer: PublicAnswer) -> None: ...

    async def validate_public_answer_draft(self, answer: PublicAnswer) -> bool: ...

    async def update_public_answer(
        self, answer: PublicAnswer, *, revoke_published_reason: str | None = None
    ) -> None: ...

    async def transition_public_answer(
        self, *, answer_id: UUID, expected_status: Sequence[PublicAnswerStatus],
        status: PublicAnswerStatus, actor_id: UUID, at: datetime,
    ) -> PublicAnswer | None: ...

    async def validate_public_answer(self, answer: PublicAnswer, *, at: datetime) -> bool: ...

    async def publish_public_answer(
        self, *, answer_id: UUID, actor_id: UUID, embedding: Sequence[float], at: datetime
    ) -> PublicAnswer | None: ...

    async def withdraw_public_answer(
        self, *, answer_id: UUID, actor_id: UUID, reason: str, at: datetime
    ) -> PublicAnswer | None: ...


class PublicAnswerEmbeddingPort(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class PublicAnswerService:
    """Owner/admin workflow for reviewed, versioned public Q&A sources."""

    def __init__(
        self, *, repository: PublicAnswerRepository, embedding_client: PublicAnswerEmbeddingPort,
        clock=lambda: datetime.now(UTC), id_factory=uuid4,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._clock = clock
        self._id_factory = id_factory

    async def list(self, space_id: UUID, *, actor_user_id: UUID) -> list[PublicAnswer]:
        await self._require_role(space_id, actor_user_id, minimum_role=SpaceRole.ADMIN)
        return await self._repository.list_public_answers(space_id)

    async def create(
        self, *, space_id: UUID, actor_user_id: UUID, category_id: UUID,
        question: str, answer: str, source_refs: Sequence[PublicAnswerSourceRef] = (),
    ) -> PublicAnswer:
        await self._require_role(space_id, actor_user_id, minimum_role=SpaceRole.ADMIN)
        now = self._clock()
        draft = PublicAnswer(
            id=self._id_factory(), space_id=space_id, category_id=category_id,
            question=_required_text(question, '问题', 2_000), answer=_required_text(answer, '答案', 20_000),
            status=PublicAnswerStatus.DRAFT, source_refs=_unique_sources(source_refs),
            created_by=actor_user_id, updated_by=actor_user_id, created_at=now, updated_at=now,
        )
        if not await self._repository.validate_public_answer_draft(draft):
            raise PublicAnswerRuleViolationError('分类和来源资料必须属于当前知识空间。')
        await self._repository.add_public_answer(draft)
        return draft

    async def update(
        self, answer_id: UUID, *, actor_user_id: UUID, category_id: UUID | None = None,
        question: str | None = None, answer: str | None = None,
        source_refs: Sequence[PublicAnswerSourceRef] | None = None,
    ) -> PublicAnswer:
        current = await self._get_answer(answer_id)
        await self._require_role(current.space_id, actor_user_id, minimum_role=SpaceRole.ADMIN)
        updated = replace(
            current,
            category_id=category_id if category_id is not None else current.category_id,
            question=_required_text(question, '问题', 2_000) if question is not None else current.question,
            answer=_required_text(answer, '答案', 20_000) if answer is not None else current.answer,
            source_refs=_unique_sources(source_refs) if source_refs is not None else current.source_refs,
            status=PublicAnswerStatus.DRAFT,
            updated_by=actor_user_id,
            reviewed_by=None,
            reviewed_at=None,
            published_version_id=None,
            published_version_number=current.published_version_number,
            withdrawal_reason=None,
            updated_at=self._clock(),
        )
        if not await self._repository.validate_public_answer_draft(updated):
            raise PublicAnswerRuleViolationError('分类和来源资料必须属于当前知识空间。')
        await self._repository.update_public_answer(
            updated,
            revoke_published_reason=(
                'CONTENT_CHANGED' if current.status is PublicAnswerStatus.PUBLISHED else None
            ),
        )
        return updated

    async def submit_for_review(self, answer_id: UUID, *, actor_user_id: UUID) -> PublicAnswer:
        current = await self._get_answer(answer_id)
        await self._require_role(current.space_id, actor_user_id, minimum_role=SpaceRole.ADMIN)
        return await self._transition(
            answer_id, expected=(PublicAnswerStatus.DRAFT, PublicAnswerStatus.WITHDRAWN),
            status=PublicAnswerStatus.IN_REVIEW, actor_id=actor_user_id,
        )

    async def approve(self, answer_id: UUID, *, actor_user_id: UUID) -> PublicAnswer:
        current = await self._get_answer(answer_id)
        await self._require_role(current.space_id, actor_user_id, minimum_role=SpaceRole.ADMIN)
        return await self._transition(
            answer_id, expected=(PublicAnswerStatus.IN_REVIEW,),
            status=PublicAnswerStatus.APPROVED, actor_id=actor_user_id,
        )

    async def publish(self, answer_id: UUID, *, actor_user_id: UUID) -> PublicAnswer:
        current = await self._get_answer(answer_id)
        await self._require_role(current.space_id, actor_user_id, minimum_role=SpaceRole.OWNER)
        if current.status is not PublicAnswerStatus.APPROVED:
            raise PublicAnswerRuleViolationError('公开稿必须先由管理员审核通过，才能发布。')
        now = self._clock()
        if not await self._repository.validate_public_answer(current, at=now):
            raise PublicAnswerRuleViolationError('公开分类或来源资料已不可用，请更新公开稿后重新审核。')
        text = f'问题：{current.question}\n答案：{current.answer}'
        vectors = await self._embedding_client.embed_documents([text])
        if len(vectors) != 1 or not vectors[0]:
            raise PublicAnswerRuleViolationError('无法生成公开稿检索向量，未发布任何内容。')
        published = await self._repository.publish_public_answer(
            answer_id=answer_id, actor_id=actor_user_id, embedding=vectors[0], at=now
        )
        if published is None:
            raise PublicAnswerRuleViolationError('公开稿状态已变化，请刷新后重试。')
        return published

    async def withdraw(self, answer_id: UUID, *, actor_user_id: UUID, reason: str = 'OWNER_WITHDRAWN') -> PublicAnswer:
        current = await self._get_answer(answer_id)
        await self._require_role(current.space_id, actor_user_id, minimum_role=SpaceRole.OWNER)
        if current.status is not PublicAnswerStatus.PUBLISHED:
            raise PublicAnswerRuleViolationError('只有已发布的公开稿可以撤回。')
        withdrawn = await self._repository.withdraw_public_answer(
            answer_id=answer_id, actor_id=actor_user_id, reason=_required_text(reason, '撤回原因', 500),
            at=self._clock(),
        )
        if withdrawn is None:
            raise PublicAnswerRuleViolationError('公开稿状态已变化，请刷新后重试。')
        return withdrawn

    async def _get_answer(self, answer_id: UUID) -> PublicAnswer:
        answer = await self._repository.get_public_answer(answer_id)
        if answer is None:
            raise PublicAnswerNotFoundError('公开问答不存在。')
        return answer

    async def _transition(
        self, answer_id: UUID, *, expected: tuple[PublicAnswerStatus, ...],
        status: PublicAnswerStatus, actor_id: UUID,
    ) -> PublicAnswer:
        answer = await self._repository.transition_public_answer(
            answer_id=answer_id, expected_status=expected, status=status,
            actor_id=actor_id, at=self._clock(),
        )
        if answer is None:
            raise PublicAnswerRuleViolationError('公开稿状态已变化，请刷新后重试。')
        return answer

    async def _require_role(self, space_id: UUID, user_id: UUID, *, minimum_role: SpaceRole) -> None:
        role = await self._repository.get_space_role(space_id=space_id, user_id=user_id)
        if role is None or not _role_at_least(role, minimum_role):
            raise SpaceAccessDeniedError('当前账号无权管理此空间的公开问答。')


_ROLE_ORDER = {
    SpaceRole.MEMBER: 0,
    SpaceRole.EDITOR: 1,
    SpaceRole.ADMIN: 2,
    SpaceRole.OWNER: 3,
}


def _role_at_least(role: SpaceRole, minimum_role: SpaceRole) -> bool:
    return _ROLE_ORDER[role] >= _ROLE_ORDER[minimum_role]


def _required_text(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise PublicAnswerRuleViolationError(f'{label}不能为空。')
    if len(normalized) > maximum:
        raise PublicAnswerRuleViolationError(f'{label}不能超过 {maximum} 个字符。')
    return normalized


def _unique_sources(sources: Sequence[PublicAnswerSourceRef]) -> tuple[PublicAnswerSourceRef, ...]:
    by_document: dict[UUID, PublicAnswerSourceRef] = {}
    for source in sources:
        if source.document_id in by_document:
            raise PublicAnswerRuleViolationError('同一公开稿不能重复选择同一份来源资料。')
        by_document[source.document_id] = source
    return tuple(by_document.values())
