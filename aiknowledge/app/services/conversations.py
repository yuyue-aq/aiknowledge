from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from difflib import SequenceMatcher
from time import perf_counter
from dataclasses import replace
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
from app.domain.rag import AnswerStatus, RagAnswer, RankedSourceChunk, SourceChunk, Usage
from app.domain.public_answers import PublicContentMode
from app.domain.spaces import PublicRetrievalScope
from app.domain.retrieval import RetrievalMetadataFilter
from app.services.usage import UsageService
from app.services.retrieval import RetrievalService
from app.services.hybrid_retrieval import HybridRetriever, branch_snapshot
from app.services.reranked_retrieval import RerankedRetriever
from app.services.rag import PROMPT_VERSION
from app.services.query_planning import complex_question


class ConversationQuestionError(ValueError):
    """Raised for a question that cannot safely enter a conversation."""


class ConversationRepository(Protocol):
    async def has_active_space(self, space_id: UUID) -> bool: ...

    async def has_space_access(self, *, space_id: UUID, user_id: UUID) -> bool: ...

    async def add_conversation(self, conversation: Conversation) -> None: ...

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...

    async def list_conversations(self, space_id: UUID) -> list[Conversation]: ...

    async def set_conversation_title(self, conversation_id: UUID, title: str) -> None: ...

    async def add_message(self, message: ConversationMessage) -> None: ...

    async def add_citations(self, citations: Sequence[CitationSnapshot]) -> None: ...

    async def add_rag_run(self, run: RagRun) -> None: ...

    async def list_messages(self, conversation_id: UUID) -> list[ConversationMessage]: ...

    async def list_citations(self, message_ids: Sequence[UUID]) -> list[CitationSnapshot]: ...

    async def list_query_diagnostics(self, message_ids: Sequence[UUID]) -> dict[UUID, dict[str, object]]: ...

    async def delete_conversation(self, conversation_id: UUID) -> None: ...

    async def retrieve_owner(
        self, *, space_id: UUID, embedding: list[float], limit: int,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> list[RetrievedChunk]: ...

    async def retrieve_public(
        self,
        *,
        scope: PublicRetrievalScope,
        embedding: list[float],
        limit: int,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> list[RetrievedChunk]: ...

    async def list_public_faq_questions(
        self, *, scope: PublicRetrievalScope, limit: int = 6
    ) -> list[str]: ...

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
    "原始文件名",
    "原文文件名",
    "列出文件名",
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
    "第一个",
    "第二个",
    "第三个",
    "前者",
    "后者",
    "上一个",
    "后一个",
    "排在",
    "最后介绍",
    "上一问",
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
        prompt_version: str = PROMPT_VERSION,
        question_rewriter: QuestionRewriterPort | None = None,
        history_limit: int = 6,
        retrieval_strategy: str = 'dense',
        reranker=None,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        usage_service: UsageService | None = None,
    ) -> None:
        if retrieval_candidate_limit <= 0:
            raise ValueError("retrieval_candidate_limit must be positive")
        if history_limit < 0:
            raise ValueError("history_limit must not be negative")
        if retrieval_strategy not in ('dense','hybrid','hybrid_rerank'):raise ValueError('Invalid retrieval strategy')
        self._strategy=retrieval_strategy
        self._repository = repository
        self._embedding_client = embedding_client
        dimension = (rag_snapshot or {}).get('embedding_dimension')
        self._retrieval = RetrievalService(embedding_client,
            expected_dimension=int(dimension) if dimension is not None else None, maximum_k=50)
        self._hybrid=HybridRetriever(self._retrieval)
        self._reranker=reranker
        self._rag_service = rag_service
        self._retrieval_candidate_limit = retrieval_candidate_limit
        self._rag_snapshot = dict(rag_snapshot or {})
        self._retrieval_config_snapshot = dict(retrieval_config_snapshot or {})
        self._prompt_version = prompt_version
        self._question_rewriter = question_rewriter or ContextualQuestionRewriter()
        self._history_limit = history_limit
        self._id_factory = id_factory
        self._clock = clock
        self._usage_service = usage_service

    async def create_owner_conversation(
        self, *, space_id: UUID, title: str | None = None, owner_user_id: UUID | None = None
    ) -> Conversation:
        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
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
        self, *, conversation_id: UUID, question: str, owner_user_id: UUID | None = None, strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> ConversationAnswer:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_owner_space(conversation.space_id, owner_user_id=owner_user_id)
        if self._usage_service is not None:
            await self._usage_service.ensure_question_allowed(
                conversation.space_id, owner_user_id=owner_user_id
            )
        return await self._ask(
            conversation=conversation,
            question=question,
            retrieve=lambda vector, limit: self._repository.retrieve_owner(
                space_id=conversation.space_id,
                embedding=vector,
                limit=limit,
                metadata_filter=metadata_filter,
            ),
            public_request=False,
            strategy=strategy,
            corpus=lambda limit:self._repository.keyword_corpus(space_id=conversation.space_id,public_scope=None,limit=limit,metadata_filter=metadata_filter),
            metadata_filter=metadata_filter,
            scope_check=self._scope_checker(conversation.space_id, owner_user_id=owner_user_id, metadata_filter=metadata_filter),
        )

    async def get_owner_conversation(
        self, conversation_id: UUID, *, owner_user_id: UUID | None = None
    ) -> ConversationDetail:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_owner_space(conversation.space_id, owner_user_id=owner_user_id)
        messages = tuple(await self._repository.list_messages(conversation.id))
        citations_by_message: dict[UUID, list[CitationSnapshot]] = {}
        for citation in await self._repository.list_citations(
            [message.id for message in messages]
        ):
            citations_by_message.setdefault(citation.message_id, []).append(citation)
        diagnostics_reader = getattr(self._repository, 'list_query_diagnostics', None)
        query_diagnostics_by_message = (
            await diagnostics_reader([message.id for message in messages])
            if callable(diagnostics_reader)
            else {}
        )
        return ConversationDetail(
            conversation=conversation,
            messages=messages,
            citations_by_message={
                message_id: tuple(citations)
                for message_id, citations in citations_by_message.items()
            },
            query_diagnostics_by_message=query_diagnostics_by_message,
        )

    async def list_owner_conversations(
        self, space_id: UUID, *, owner_user_id: UUID | None = None
    ) -> tuple[Conversation, ...]:
        """Return only owner conversations from a live knowledge space.

        The repository query performs the kind and space filtering as well, so
        callers cannot accidentally surface public guest conversations in the
        owner workspace.  The active-space check keeps deleted spaces from
        leaking historical metadata through this collection endpoint.
        """

        await self._require_owner_space(space_id, owner_user_id=owner_user_id)
        conversations = await self._repository.list_conversations(space_id)
        return tuple(
            conversation
            for conversation in conversations
            if conversation.kind is ConversationKind.OWNER
        )

    async def delete_owner_conversation(
        self, conversation_id: UUID, *, owner_user_id: UUID | None = None
    ) -> None:
        conversation = await self._require_conversation(conversation_id)
        if conversation.kind is not ConversationKind.OWNER:
            raise ConversationAccessDeniedError("对话访问范围不匹配。")
        await self._require_owner_space(conversation.space_id, owner_user_id=owner_user_id)
        await self._repository.delete_conversation(conversation.id)
        await self._repository.commit()

    async def ask_public(
        self,
        *,
        conversation_id: UUID,
        scope: PublicRetrievalScope,
        question: str,
        strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None,
    ) -> ConversationAnswer:
        if scope.content_mode is PublicContentMode.PUBLISHED_ANSWERS and metadata_filter is not None and (
            metadata_filter.tag_ids or metadata_filter.formats or metadata_filter.version_min is not None
            or metadata_filter.version_max is not None or metadata_filter.valid_from is not None
            or metadata_filter.valid_to is not None
        ):
            raise ConversationQuestionError('已审核问答分享链接只支持分类筛选。')
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
            retrieve=lambda vector, limit: self._repository.retrieve_public(
                scope=scope,
                embedding=vector,
                limit=limit,
                metadata_filter=metadata_filter,
            ),
            public_request=True,
            strategy=strategy,
            corpus=lambda limit:self._repository.keyword_corpus(space_id=scope.space_id,public_scope=scope,limit=limit,metadata_filter=metadata_filter),
            metadata_filter=metadata_filter,
            scope_check=self._scope_checker(scope.space_id, public_scope=scope, metadata_filter=metadata_filter),
        )

    async def list_public_faq_questions(
        self, *, scope: PublicRetrievalScope, limit: int = 6
    ) -> list[str]:
        if scope.content_mode is not PublicContentMode.PUBLISHED_ANSWERS or limit <= 0:
            return []
        reader = getattr(self._repository, 'list_public_faq_questions', None)
        if reader is None:
            return []
        return await reader(scope=scope, limit=min(limit, 6))

    async def answer_owner(self, *, space_id: UUID, question: str, strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None) -> RagAnswer:
        """Internal evaluation entry point; unlike ``ask_owner`` it stores no history."""

        await self._require_active_space(space_id)
        answer, _ = await self._generate_answer(
            question=self._normalize_question(question),
            retrieve=lambda vector, limit: self._repository.retrieve_owner(
                space_id=space_id,
                embedding=vector,
                limit=limit,
                metadata_filter=metadata_filter,
            ),
            public_request=False,
            strategy=strategy,
            corpus=lambda limit:self._repository.keyword_corpus(space_id=space_id,public_scope=None,limit=limit,metadata_filter=metadata_filter),
            metadata_filter=metadata_filter,
            scope_check=self._scope_checker(space_id, metadata_filter=metadata_filter),
        )
        return answer

    async def answer_public(
        self,
        *,
        space_id: UUID,
        category_ids: tuple[UUID, ...],
        question: str,
        strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None,
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
            retrieve=lambda vector, limit: self._repository.retrieve_public(
                scope=scope,
                embedding=vector,
                limit=limit,
                metadata_filter=metadata_filter,
            ),
            public_request=True,
            strategy=strategy,
            corpus=lambda limit:self._repository.keyword_corpus(space_id=space_id,public_scope=scope,limit=limit,metadata_filter=metadata_filter),
            metadata_filter=metadata_filter,
            scope_check=self._scope_checker(space_id, public_scope=scope, metadata_filter=metadata_filter),
        )
        return answer

    async def _ask(
        self,
        *,
        conversation: Conversation,
        question: str,
        retrieve: Callable,
        corpus: Callable | None = None,
        strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None,
        public_request: bool,
        scope_check: Callable | None = None,
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
            corpus=corpus,
            strategy=strategy,
            public_request=public_request,
            scope_check=scope_check,
        )
        query_diagnostics = (
            self._build_query_diagnostics(
                original_question=normalized_question,
                retrieval_question=rewritten_question,
                answer=answer,
            )
            if not public_request
            else None
        )
        if query_diagnostics is not None:
            answer.execution_snapshot = {
                **(answer.execution_snapshot or {}),
                'query_diagnostics': query_diagnostics,
            }
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
                model_snapshot={**self._rag_snapshot,
                    'user_message_id': str(user_message.id),
                    'reranker':(answer.execution_snapshot or {}).get('retrieval_config',{}).get('reranker',{}).get('model','disabled-for-rrf') if (answer.execution_snapshot or {}).get('retrieval_strategy') in ('hybrid','hybrid_rerank') else self._rag_snapshot.get('reranker','lexical-dense-v1'),
                    'execution_timings_ms':(answer.execution_snapshot or {}).get('timings_ms',{}),
                    'context_chunk_ids':(answer.execution_snapshot or {}).get('context_chunk_ids',[]),
                    'retrieved_chunks':(answer.execution_snapshot or {}).get('retrieved_chunks',[]),
                    'retrieval_queries':(answer.execution_snapshot or {}).get('retrieval_queries',[]),
                    **({'query_diagnostics': query_diagnostics} if query_diagnostics is not None else {})},
                retrieval_config_snapshot={
                    "candidate_limit": self._retrieval_candidate_limit,
                    **self._retrieval_config_snapshot,
                    **(answer.execution_snapshot or {}).get('retrieval_config',{}),
                    'metadata_filter': (metadata_filter or RetrievalMetadataFilter()).snapshot(),
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
            scope_snapshot=getattr(scope_check, 'snapshot', None),
            query_diagnostics=query_diagnostics,
        )

    async def _generate_answer(
        self,
        *,
        question: str,
        retrieve: Callable,
        corpus: Callable | None = None,
        strategy: str | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None,
        public_request: bool,
        scope_check: Callable | None = None,
    ) -> tuple[RagAnswer, tuple[RetrievedChunk, ...]]:
        strategy=strategy or self._strategy
        if strategy not in ('dense','hybrid','hybrid_rerank'):raise ConversationQuestionError('不支持的检索方式。')
        config=(RerankedRetriever(self._hybrid,self._reranker).config if self._reranker is not None else {'strategy':'hybrid_rerank'}) if strategy=='hybrid_rerank' else self._hybrid.config if strategy=='hybrid' else {'strategy':'dense','score_kind':'cosine'}
        config = {**config, 'metadata_filter': (metadata_filter or RetrievalMetadataFilter()).snapshot()}
        phase_started = perf_counter()
        if public_request and self._is_public_recovery_request(question):
            return (
                RagAnswer(
                    status=AnswerStatus.OUT_OF_SCOPE,
                    answer="公开访问仅提供开放分类内的归纳回答，不能输出或恢复原始资料。",
                    execution_snapshot={'retrieval_strategy':strategy,'retrieval_config':config,'context_chunk_ids':[]},
                ),
                (),
            )
        if scope_check is not None:
            await scope_check(())
        planning_usage = Usage()
        planned_queries = ()
        query_evidence = []
        planning_ms = 0.
        try:
            async def fetch(vector, limit):
                return await retrieve(vector,limit)
            if strategy=='hybrid_rerank':
                async def validate(items):
                    if scope_check is not None:await scope_check(items)
                result=await RerankedRetriever(self._hybrid,self._reranker).search(question=question,fetch=fetch,corpus=corpus,
                    top_k=self._retrieval_candidate_limit,validate=validate)
                config=result.config_snapshot
            elif strategy=='hybrid':
                result=await self._hybrid.search(question=question,fetch=fetch,corpus=corpus,top_k=self._retrieval_candidate_limit)
                config={**config,'branches':branch_snapshot(result)}
                if scope_check is not None:
                    await scope_check(tuple({x.id:x for items in result.branches.values() for x in items}.values()))
            else:
                result = await self._retrieval.search(question=question, fetch=fetch, top_k=self._retrieval_candidate_limit)
            candidates = result.items
            query_evidence.append({
                'kind': 'primary',
                'query': question,
                'items': self._query_evidence_snapshot(candidates),
            })
            retrieval_timings=dict(result.timings_ms)
            planner=getattr(self._rag_service,'plan_retrieval',None)
            if strategy=='dense' and callable(planner) and complex_question(question):
                if scope_check is not None:await scope_check(tuple(candidates))
                planning_started=perf_counter()
                plan=await planner(question,candidates)
                planning_ms=(perf_counter()-planning_started)*1000
                planning_usage=plan.usage
                planned_queries=plan.queries[:4]
                merged={x.id:x for x in candidates}
                leaders=[]
                for subquery in planned_queries:
                    extra=await self._retrieval.search(question=subquery,fetch=fetch,top_k=self._retrieval_candidate_limit)
                    query_evidence.append({
                        'kind': 'subquery',
                        'query': subquery,
                        'items': self._query_evidence_snapshot(extra.items),
                    })
                    for key in ('embedding','search','total'):retrieval_timings[key]+=extra.timings_ms[key]
                    for index,item in enumerate(extra.items):
                        if index<2 and item.id not in leaders:leaders.append(item.id)
                        if item.id not in merged or item.score>merged[item.id].score:merged[item.id]=item
                ordered=list(dict.fromkeys([*leaders,*merged]))[:50]
                priorities={cid:index for index,cid in enumerate(leaders)}
                candidates=tuple(replace(merged[cid],context_priority=priorities.get(cid)) for cid in ordered)
        except (RuntimeError, ValueError) as failure:
            return (
                RagAnswer(
                    status=AnswerStatus.FAILED,
                    answer="模型服务暂时不可用，请稍后重试。",
                    execution_snapshot={'retrieval_strategy':strategy,'retrieval_config':config,
                        'failure_code':getattr(failure,'code','RETRIEVAL_UNAVAILABLE'),'context_chunk_ids':[]},
                ),
                (),
            )

        immutable_candidates = self._deduplicate_candidates(candidates)
        if scope_check is not None:
            await scope_check(immutable_candidates)
        ranked = [
            RankedSourceChunk(
                source=SourceChunk(
                    id=str(candidate.id),
                    title='公开资料' if public_request else candidate.document_name,
                    content=candidate.content,
                    heading_path=candidate.heading_path,
                    context_priority=candidate.context_priority,
                ),
                score=candidate.score,
                score_kind=candidate.score_kind,
            )
            for candidate in immutable_candidates
        ]
        generation_started = perf_counter()
        try:
            answer = await self._rag_service.answer_ranked(question, ranked)
        except (RuntimeError, ValueError):
            answer = RagAnswer(
                status=AnswerStatus.FAILED,
                answer="模型服务暂时不可用，请稍后重试。",
                execution_snapshot={'failure_code': 'GENERATION_UNAVAILABLE'},
            )
        generation_ms = (perf_counter()-generation_started)*1000
        answer.usage=Usage(answer.usage.prompt_tokens+planning_usage.prompt_tokens,
            answer.usage.completion_tokens+planning_usage.completion_tokens,answer.usage.total_tokens+planning_usage.total_tokens)
        if scope_check is not None:
            await scope_check(immutable_candidates)
        answer = self._ensure_citations_are_retrieved(answer, immutable_candidates)
        answer.execution_snapshot = {
            **(answer.execution_snapshot or {}),
            'schema_version': 3,
            'retrieval_strategy':strategy,
            'retrieval_config':config,
            'question': question,
            'retrieval_queries':list(planned_queries),
            'query_evidence':query_evidence,
            'timings_ms': {**retrieval_timings,'retrieval_total':retrieval_timings['total'],
                'query_planning':round(planning_ms,3),
                'generation':round(generation_ms,3),'total':round((perf_counter()-phase_started)*1000,3)},
            'retrieved_chunks': [{
                'chunk_id': str(item.id), 'document_id': str(item.document_id),
                'document_version_id': str(item.document_version_id) if item.document_version_id else None,
                'rank': rank, 'score': item.score, 'score_kind':item.score_kind, 'content_hash': item.content_hash,
                'dense_rank':item.dense_rank,'bm25_rank':item.bm25_rank,'fusion_rank':item.fusion_rank,
                'dense_score':item.dense_score,'bm25_score':item.bm25_score,
                'fusion_score':item.fusion_score,'rerank_rank':item.rerank_rank,'rerank_score':item.rerank_score,
                'source_block_id': item.source_block_id, 'char_start': item.char_start, 'char_end': item.char_end,
            } for rank, item in enumerate(immutable_candidates, 1)],
        }
        answer.retrieval_chunks = immutable_candidates
        return (
            answer,
            immutable_candidates,
        )

    @staticmethod
    def _build_query_diagnostics(
        *, original_question: str, retrieval_question: str, answer: RagAnswer
    ) -> dict[str, object]:
        snapshot = answer.execution_snapshot or {}
        context_ids = {str(value) for value in snapshot.get('context_chunk_ids', [])}
        if not context_ids:
            context_ids = {str(citation.source_chunk_id) for citation in answer.citations}
        raw_queries = snapshot.get('query_evidence', [])
        queries = []
        if isinstance(raw_queries, list):
            for raw in raw_queries:
                if not isinstance(raw, dict) or not isinstance(raw.get('query'), str):
                    continue
                items = raw.get('items', ())
                evidence = []
                for rank, item in enumerate(items, 1):
                    if isinstance(item, RetrievedChunk):
                        chunk_id = str(item.id)
                        document_name = item.document_name
                        ordinal = item.ordinal
                        score = item.score
                        score_kind = item.score_kind
                    elif isinstance(item, dict):
                        chunk_id = item.get('chunk_id')
                        document_name = item.get('document_name')
                        ordinal = item.get('ordinal')
                        score = item.get('score')
                        score_kind = item.get('score_kind')
                    else:
                        continue
                    if not isinstance(chunk_id, str):
                        continue
                    evidence.append({
                        'chunk_id': chunk_id,
                        'document_name': document_name,
                        'ordinal': ordinal,
                        'rank': rank,
                        'score': score,
                        'score_kind': score_kind,
                        'selected_for_context': chunk_id in context_ids,
                    })
                queries.append({
                    'kind': raw.get('kind') if raw.get('kind') in ('primary', 'subquery') else 'primary',
                    'query': raw['query'],
                    'evidence': evidence,
                })
        return {
            'original_question': original_question,
            'retrieval_question': retrieval_question,
            'was_rewritten': original_question != retrieval_question,
            'queries': queries,
        }

    @staticmethod
    def _query_evidence_snapshot(items: Sequence[RetrievedChunk]) -> list[dict[str, object]]:
        """Return JSON-safe, content-free references for retrieval diagnostics."""
        return [
            {
                'chunk_id': str(item.id),
                'document_id': str(item.document_id),
                'document_version_id': (
                    str(item.document_version_id) if item.document_version_id else None
                ),
                'document_name': item.document_name,
                'ordinal': item.ordinal,
                'score': item.score,
                'score_kind': item.score_kind,
                'source_block_id': item.source_block_id,
                'char_start': item.char_start,
                'char_end': item.char_end,
            }
            for item in items
        ]

    def _scope_checker(self, space_id: UUID, *, owner_user_id: UUID | None = None, public_scope: PublicRetrievalScope | None = None,
        metadata_filter: RetrievalMetadataFilter | None = None):
        reader = getattr(self._repository, 'generation_scope_snapshot', None)
        validator = getattr(self._repository, 'validate_generation_chunks', None)
        if reader is None or validator is None:
            # Compatibility for injected V1 test ports. The production SQL
            # repository implements both methods and always checks live scope.
            return None
        initial = None
        async def check(chunks):
            nonlocal initial
            snapshot = await reader(space_id=space_id, user_id=owner_user_id, public_scope=public_scope)
            if snapshot is None or (initial is not None and snapshot != initial):
                raise ConversationAccessDeniedError('资料或访问范围已变化，请重新提问。')
            if initial is None:
                initial = snapshot
                check.snapshot = snapshot
            if not await validator(space_id=space_id, public_scope=public_scope, chunk_ids=tuple(x.id for x in chunks), metadata_filter=metadata_filter):
                raise ConversationAccessDeniedError('引用资料已不可用，请重新提问。')
            await self._repository.commit()
        return check

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
                chunk_id=(
                    None if candidate_by_id[citation.source_chunk_id].public_answer_version_id
                    else candidate_by_id[citation.source_chunk_id].id
                ),
                document_name=(
                    candidate_by_id[citation.source_chunk_id].public_answer_title
                    or candidate_by_id[citation.source_chunk_id].document_name
                ),
                quoted_text=(
                    candidate_by_id[citation.source_chunk_id].public_answer_text
                    or candidate_by_id[citation.source_chunk_id].content
                ),
                page_number=candidate_by_id[citation.source_chunk_id].page_number,
                ordinal=candidate_by_id[citation.source_chunk_id].ordinal,
                score=citation.score,
                public_answer_version_id=candidate_by_id[citation.source_chunk_id].public_answer_version_id,
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
            execution_snapshot=answer.execution_snapshot,
        )

    async def _require_active_space(self, space_id: UUID) -> None:
        if not await self._repository.has_active_space(space_id):
            raise ConversationNotFoundError("知识空间不存在。")

    async def _require_owner_space(self, space_id: UUID, *, owner_user_id: UUID | None) -> None:
        if owner_user_id is None:
            await self._require_active_space(space_id)
            return
        checker = getattr(self._repository, "has_space_access", None)
        if checker is None or not await checker(space_id=space_id, user_id=owner_user_id):
            raise ConversationNotFoundError("知识空间不存在。")

    async def _require_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = await self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError("对话不存在。")
        return conversation

    @staticmethod
    def _is_public_recovery_request(question: str) -> bool:
        normalized = question.casefold()
        if any(pattern in normalized for pattern in _PUBLIC_RECOVERY_REQUESTS):
            return True
        # Reject explicit imperatives before retrieval/generation. Explanatory
        # questions about the permission policy still use scoped retrieval.
        command = normalized.lstrip('请')
        return command.startswith(('忽略权限', '绕过权限', '无视权限')) and any(
            marker in command for marker in ('私密资料', '私有资料', '内部密钥', '内部口令')
        )

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
