from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from difflib import SequenceMatcher
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from app.domain.conversations import (
    CitationSnapshot,
    Conversation,
    ConversationAccessDeniedError,
    ConversationAnswer,
    ConversationDetail,
    ConversationKind,
    ConversationMessage,
    ConversationNotFoundError,
    MessageRole,
    RagRun,
    RetrievedChunk,
)
from app.domain.rag import AnswerStatus, RagAnswer, RankedSourceChunk, SourceChunk
from app.domain.spaces import PublicRetrievalScope


class ConversationQuestionError(ValueError):
    """Raised for a question that cannot safely enter a conversation."""


class ConversationRepository(Protocol):
    async def has_active_space(self, space_id: UUID) -> bool: ...

    async def add_conversation(self, conversation: Conversation) -> None: ...

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...

    async def list_conversations(self, space_id: UUID) -> list[Conversation]: ...

    async def set_conversation_title(self, conversation_id: UUID, title: str) -> None: ...

    async def add_message(self, message: ConversationMessage) -> None: ...

    async def add_citations(self, citations: Sequence[CitationSnapshot]) -> None: ...

    async def add_rag_run(self, run: RagRun) -> None: ...

    async def list_messages(self, conversation_id: UUID) -> list[ConversationMessage]: ...

    async def list_citations(self, message_ids: Sequence[UUID]) -> list[CitationSnapshot]: ...

    async def delete_conversation(self, conversation_id: UUID) -> None: ...

    async def retrieve_owner(
        self, *, space_id: UUID, embedding: list[float], limit: int
    ) -> list[RetrievedChunk]: ...

    async def retrieve_public(
        self,
        *,
        scope: PublicRetrievalScope,
        embedding: list[float],
        limit: int,
    ) -> list[RetrievedChunk]: ...

    async def commit(self) -> None: ...


class QueryEmbeddingPort(Protocol):
    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]: ...


class RankedAnswerPort(Protocol):
    async def answer_ranked(
        self, question: str, chunks: Sequence[RankedSourceChunk]
    ) -> RagAnswer: ...


_PUBLIC_RECOVERY_REQUESTS = (
    "逐字输出",
    "全文",
    "完整原文",
    "所有段落",
    "列出所有段落",
    "文件列表",
    "导出原文",
)
_FOLLOW_UP_MARKERS = (
    "它",
    "他",
    "她",
    "这个",
    "那个",
    "其",
    "上述",
    "前面",
    "继续",
    "还有",
    "再说",
    "详细",
    "该",
)
_MAX_QUESTION_LENGTH = 2_000
_SIMILARITY_DEDUP_THRESHOLD = 0.92
_SIMILARITY_DEDUP_MIN_LENGTH = 32


class QuestionRewriterPort(Protocol):
    async def rewrite(
        self, *, question: str, history: Sequence[ConversationMessage]
    ) -> str: ...


class ContextualQuestionRewriter:
    """Expand pronoun-based follow-ups without treating answers as evidence."""

    async def rewrite(
        self, *, question: str, history: Sequence[ConversationMessage]
    ) -> str:
        previous_user = next(
            (
                message
                for message in reversed(history)
                if message.role is MessageRole.USER
            ),
            None,
        )
        if previous_user is None or not any(
            marker in question for marker in _FOLLOW_UP_MARKERS
        ):
            return question
        prefix = "上一轮问题："
        suffix = f"\n本轮追问：{question}"
        history_budget = _MAX_QUESTION_LENGTH - len(prefix) - len(suffix)
        if history_budget <= 0:
            return question
        previous = previous_user.content[:history_budget]
        return f"{prefix}{previous}{suffix}"


class ConversationService:
    """Coordinates durable, evidence-bound owner and visitor question flows.

    The public method always receives a freshly resolved ``PublicRetrievalScope``
    from the HTTP dependency.  It verifies that a conversation remains bound to
    that exact live share link before querying chunks.
    """

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        embedding_client: QueryEmbeddingPort,
        rag_service: RankedAnswerPort,
        retrieval_candidate_limit: int,
        rag_snapshot: dict[str, object] | None = None,
        retrieval_config_snapshot: dict[str, object] | None = None,
        prompt_version: str = "rag-prompt-v1",
        question_rewriter: QuestionRewriterPort | None = None,
        history_limit: int = 6,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if retrieval_candidate_limit <= 0:
            raise ValueError("retrieval_candidate_limit must be positive")
        if history_limit < 0:
            raise ValueError("history_limit must not be negative")
        self._repository = repository
        self._embedding_client = embedding_client
        self._rag_service = rag_service
        self._retrieval_candidate_limit = retrieval_candidate_limit
        self._rag_snapshot = dict(rag_snapshot or {})
        self._retrieval_config_snapshot = dict(retrieval_config_snapshot or {})
        self._prompt_version = prompt_version
        self._question_rewriter = question_rewriter or ContextualQuestionRewriter()
        self._history_limit = history_limit
        self._id_factory = id_factory
        self._clock = clock

    async def create_owner_conversation(
        self, *, space_id: UUID, title: str | None = None
    ) -> Conversation:
        await self._require_active_space(space_id)
        conversation = Conversation(
            id=self._id_factory(),
            space_id=space_id,
            kind=ConversationKind.OWNER,
            share_link_id=None,
            title=self._normalize_optional_title(title),
            created_at=self._now(),
            updated_at=self._now(),
        )
        await self._repository.add_conversation(conversation)
        await self._repository.commit()
        return conversation

    async def create_public_conversation(
        self, *, scope: PublicRetrievalScope, title: str | None = None
    ) -> Conversation:
        await self._require_active_space(scope.space_id)
        conversation = Conversation(
            id=self._id_factory(),
            space_id=scope.space_id,
            kind=ConversationKind.PUBLIC,
            share_link_id=scope.share_link_id,
            title=self._normalize_optional_title(title),
            created_at=self._now(),
            updated_at=self._now(),
        )
        await self._repository.add_conversation(conversation)
        await self._repository.commit()
        return conversation

    async def ask_owner(
        self, *, conversation_id: UUID, question: str
    ) -> ConversationAnswer:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_active_space(conversation.space_id)
        return await self._ask(
            conversation=conversation,
            question=question,
            retrieve=lambda vector: self._repository.retrieve_owner(
                space_id=conversation.space_id,
                embedding=vector,
                limit=self._retrieval_candidate_limit,
            ),
            public_request=False,
        )

    async def get_owner_conversation(self, conversation_id: UUID) -> ConversationDetail:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_active_space(conversation.space_id)
        messages = tuple(await self._repository.list_messages(conversation.id))
        citations_by_message: dict[UUID, list[CitationSnapshot]] = {}
        for citation in await self._repository.list_citations(
            [message.id for message in messages]
        ):
            citations_by_message.setdefault(citation.message_id, []).append(citation)
        return ConversationDetail(
            conversation=conversation,
            messages=messages,
            citations_by_message={
                message_id: tuple(citations)
                for message_id, citations in citations_by_message.items()
            },
        )

    async def list_owner_conversations(self, space_id: UUID) -> tuple[Conversation, ...]:
        """Return only owner conversations from a live knowledge space.

        The repository query performs the kind and space filtering as well, so
        callers cannot accidentally surface public guest conversations in the
        owner workspace.  The active-space check keeps deleted spaces from
        leaking historical metadata through this collection endpoint.
        """

        await self._require_active_space(space_id)
        conversations = await self._repository.list_conversations(space_id)
        return tuple(
            conversation
            for conversation in conversations
            if conversation.kind is ConversationKind.OWNER
        )

    async def delete_owner_conversation(self, conversation_id: UUID) -> None:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_active_space(conversation.space_id)
        await self._repository.delete_conversation(conversation.id)
        await self._repository.commit()

    async def ask_public(
        self,
        *,
        conversation_id: UUID,
        scope: PublicRetrievalScope,
        question: str,
    ) -> ConversationAnswer:
        conversation = await self._require_conversation(conversation_id)
        if (
            conversation.kind is not ConversationKind.PUBLIC
            or conversation.space_id != scope.space_id
            or conversation.share_link_id != scope.share_link_id
        ):
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        # The incoming scope is live-resolved by the API dependency on every
        # request.  This second check prevents stale/deleted-space retrieval
        # when the service is used outside HTTP.
        await self._require_active_space(scope.space_id)
        return await self._ask(
            conversation=conversation,
            question=question,
            retrieve=lambda vector: self._repository.retrieve_public(
                scope=scope,
                embedding=vector,
                limit=self._retrieval_candidate_limit,
            ),
            public_request=True,
        )

    async def answer_owner(self, *, space_id: UUID, question: str) -> RagAnswer:
        """Internal evaluation entry point; unlike ``ask_owner`` it stores no history."""

        await self._require_active_space(space_id)
        answer, _ = await self._generate_answer(
            question=self._normalize_question(question),
            retrieve=lambda vector: self._repository.retrieve_owner(
                space_id=space_id,
                embedding=vector,
                limit=self._retrieval_candidate_limit,
            ),
            public_request=False,
        )
        return answer

    async def answer_public(
        self,
        *,
        space_id: UUID,
        category_ids: tuple[UUID, ...],
        question: str,
    ) -> RagAnswer:
        """Internal evaluation entry point using the identical public SQL scope."""

        await self._require_active_space(space_id)
        scope = PublicRetrievalScope(
            # This synthetic value is never exposed or persisted.  The
            # evaluator is trusted server-side and the query uses only its
            # explicitly supplied scope; public browser paths still resolve a
            # live share link for every request.
            share_link_id=UUID(int=0),
            space_id=space_id,
            category_ids=category_ids,
        )
        answer, _ = await self._generate_answer(
            question=self._normalize_question(question),
            retrieve=lambda vector: self._repository.retrieve_public(
                scope=scope,
                embedding=vector,
                limit=self._retrieval_candidate_limit,
            ),
            public_request=True,
        )
        return answer

    async def _ask(
        self,
        *,
        conversation: Conversation,
        question: str,
        retrieve: Callable[[list[float]], Awaitable[list[RetrievedChunk]]],
        public_request: bool,
    ) -> ConversationAnswer:
        normalized_question = self._normalize_question(question)
        history = await self._repository.list_messages(conversation.id)
        recent_history = (
            tuple(history[-self._history_limit :]) if self._history_limit else ()
        )
        rewritten_question = self._normalize_question(
            await self._question_rewriter.rewrite(
                question=normalized_question,
                history=recent_history,
            )
        )
        user_message = ConversationMessage(
            id=self._id_factory(),
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=normalized_question,
            created_at=self._now(),
        )
        await self._repository.add_message(user_message)

        started_at = perf_counter()
        answer, candidates = await self._generate_answer(
            question=rewritten_question,
            retrieve=retrieve,
            public_request=public_request,
        )
        assistant_message = ConversationMessage(
            id=self._id_factory(),
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer.answer,
            answer_status=answer.status,
            model=answer.model,
            prompt_tokens=answer.usage.prompt_tokens or None,
            completion_tokens=answer.usage.completion_tokens or None,
            created_at=self._now(),
        )
        await self._repository.add_message(assistant_message)
        citations = self._citation_snapshots(
            answer=answer,
            message_id=assistant_message.id,
            candidates=candidates,
        )
        if citations:
            await self._repository.add_citations(citations)
        await self._repository.add_rag_run(
            RagRun(
                id=self._id_factory(),
                trace_id=self._id_factory(),
                message_id=assistant_message.id,
                prompt_version=self._prompt_version,
                rewritten_question=rewritten_question,
                model_snapshot=dict(self._rag_snapshot),
                retrieval_config_snapshot={
                    "candidate_limit": self._retrieval_candidate_limit,
                    **self._retrieval_config_snapshot,
                },
                retrieved_chunk_ids=tuple(candidate.id for candidate in candidates),
                selected_chunk_ids=tuple(
                    citation.chunk_id
                    for citation in citations
                    if citation.chunk_id is not None
                ),
                input_tokens=answer.usage.prompt_tokens or None,
                output_tokens=answer.usage.completion_tokens or None,
                first_token_latency_ms=None,
                total_latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
                estimated_cost=None,
                created_at=self._now(),
            )
        )
        if conversation.title is None:
            await self._repository.set_conversation_title(
                conversation.id, normalized_question[:200]
            )
        await self._repository.commit()
        return ConversationAnswer(
            user=user_message,
            assistant=assistant_message,
            citations=citations,
        )

    async def _generate_answer(
        self,
        *,
        question: str,
        retrieve: Callable[[list[float]], Awaitable[list[RetrievedChunk]]],
        public_request: bool,
    ) -> tuple[RagAnswer, tuple[RetrievedChunk, ...]]:
        if public_request and self._is_public_recovery_request(question):
            return (
                RagAnswer(
                    status=AnswerStatus.OUT_OF_SCOPE,
                    answer="公开访问仅提供开放分类内的归纳回答，不能输出或恢复原始资料。",
                ),
                (),
            )
        try:
            vectors = await self._embedding_client.embed_queries([question])
            if len(vectors) != 1 or not vectors[0]:
                raise ValueError("Embedding client must return one non-empty query vector")
            candidates = await retrieve(vectors[0])
        except (RuntimeError, ValueError):
            return (
                RagAnswer(
                    status=AnswerStatus.FAILED,
                    answer="模型服务暂时不可用，请稍后重试。",
                ),
                (),
            )

        immutable_candidates = self._deduplicate_candidates(candidates)
        ranked = [
            RankedSourceChunk(
                source=SourceChunk(
                    id=str(candidate.id),
                    title=candidate.document_name,
                    content=candidate.content,
                ),
                score=candidate.score,
            )
            for candidate in immutable_candidates
        ]
        try:
            answer = await self._rag_service.answer_ranked(question, ranked)
        except (RuntimeError, ValueError):
            return (
                RagAnswer(
                    status=AnswerStatus.FAILED,
                    answer="模型服务暂时不可用，请稍后重试。",
                ),
                immutable_candidates,
            )
        return (
            self._ensure_citations_are_retrieved(answer, immutable_candidates),
            immutable_candidates,
        )

    def _citation_snapshots(
        self,
        *,
        answer: RagAnswer,
        message_id: UUID,
        candidates: Sequence[RetrievedChunk],
    ) -> tuple[CitationSnapshot, ...]:
        if answer.status is not AnswerStatus.ANSWERED:
            return ()
        candidate_by_id = {str(candidate.id): candidate for candidate in candidates}
        return tuple(
            CitationSnapshot(
                id=self._id_factory(),
                message_id=message_id,
                chunk_id=candidate_by_id[citation.source_chunk_id].id,
                document_name=candidate_by_id[citation.source_chunk_id].document_name,
                quoted_text=candidate_by_id[citation.source_chunk_id].content,
                page_number=candidate_by_id[citation.source_chunk_id].page_number,
                ordinal=candidate_by_id[citation.source_chunk_id].ordinal,
                score=citation.score,
            )
            for citation in answer.citations
        )

    @staticmethod
    def _deduplicate_candidates(
        candidates: Sequence[RetrievedChunk],
    ) -> tuple[RetrievedChunk, ...]:
        """Remove repeated snippets from one document before model prompting.

        Vector search can return the same chunk more than once when overlapping
        indexes or duplicate ingestion records exist.  Retrieval is already
        ordered by relevance, so keeping the first occurrence preserves the
        highest-ranked hit while keeping the original ordering for citations.
        Whitespace is normalized only for comparison; the original text remains
        available to the model and in audit snapshots.
        """

        seen: dict[UUID, list[str]] = {}
        deduplicated: list[RetrievedChunk] = []
        for candidate in candidates:
            normalized_content = " ".join(candidate.content.split())
            document_contents = seen.setdefault(candidate.document_id, [])
            is_duplicate = normalized_content in document_contents
            if not is_duplicate and len(normalized_content) >= _SIMILARITY_DEDUP_MIN_LENGTH:
                is_duplicate = any(
                    len(previous) >= _SIMILARITY_DEDUP_MIN_LENGTH
                    and SequenceMatcher(
                        None,
                        normalized_content,
                        previous,
                        autojunk=False,
                    ).ratio()
                    >= _SIMILARITY_DEDUP_THRESHOLD
                    for previous in document_contents
                )
            if is_duplicate:
                continue
            document_contents.append(normalized_content)
            deduplicated.append(candidate)
        return tuple(deduplicated)

    @staticmethod
    def _ensure_citations_are_retrieved(
        answer: RagAnswer, candidates: Sequence[RetrievedChunk]
    ) -> RagAnswer:
        if answer.status is not AnswerStatus.ANSWERED:
            return answer
        candidate_ids = {str(candidate.id) for candidate in candidates}
        if answer.citations and all(
            citation.source_chunk_id in candidate_ids for citation in answer.citations
        ):
            return answer
        return RagAnswer(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer="当前资料中没有足够依据回答这个问题。",
            model=answer.model,
            usage=answer.usage,
        )

    async def _require_active_space(self, space_id: UUID) -> None:
        if not await self._repository.has_active_space(space_id):
            raise ConversationNotFoundError("知识空间不存在。")

    async def _require_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = await self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError("对话不存在。")
        return conversation

    @staticmethod
    def _is_public_recovery_request(question: str) -> bool:
        normalized = question.casefold()
        return any(pattern in normalized for pattern in _PUBLIC_RECOVERY_REQUESTS)

    @staticmethod
    def _normalize_question(question: str) -> str:
        normalized = question.strip()
        if not normalized:
            raise ConversationQuestionError("问题不能为空。")
        if len(normalized) > _MAX_QUESTION_LENGTH:
            raise ConversationQuestionError("问题不能超过 2000 个字符。")
        return normalized

    @staticmethod
    def _normalize_optional_title(title: str | None) -> str | None:
        if title is None:
            return None
        normalized = title.strip()
        if len(normalized) > 200:
            raise ConversationQuestionError("对话标题不能超过 200 个字符。")
        return normalized or None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)
