from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_database_session
from app.core.errors import AppError
from app.domain.retrieval import RetrievalError, RetrievalRun
from app.domain.users import User
from app.api.v1.documents import DocumentResponse
from app.api.v1.evaluations import get_evaluation_service, _translate_evaluation_error

router = APIRouter(tags=['retrieval'])


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20, strict=True)
    strategy: Literal['dense','bm25','hybrid'] = 'dense'


class RetrievalItem(BaseModel):
    rank: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID | None
    document_name: str
    content: str
    page_number: int | None
    ordinal: int
    score: float
    score_kind: Literal['cosine','bm25','rrf'] = 'cosine'
    dense_rank: int | None = None
    bm25_rank: int | None = None
    fusion_rank: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    source_block_id: str | None
    char_start: int | None
    char_end: int | None
    content_hash: str | None
    token_count: int | None


class RetrievalResponse(BaseModel):
    status: str = 'COMPLETED'
    run_id: UUID
    space_id: UUID
    question: str
    top_k: int
    access_revision: int
    knowledge_revision: int
    model_name: str
    created_at: datetime
    timings_ms: dict[str, float]
    items: list[RetrievalItem]
    unavailable_chunk_ids: list[UUID]
    strategy: Literal['dense','bm25','hybrid'] = 'dense'
    score_kind: Literal['cosine','bm25','rrf'] = 'cosine'
    config_snapshot: dict[str, object] = Field(default_factory=dict)
    branches: dict[str,list[RetrievalItem]] = Field(default_factory=dict)

    @classmethod
    def build(cls, run: RetrievalRun, chunks):
        by_id = {x.id: x for x in chunks}
        saved_branches=run.config_snapshot.get('branches',{})
        branch_maps={name:{UUID(item['chunk_id']):item for item in values} for name,values in saved_branches.items()}
        kind={'dense':'cosine','bm25':'bm25','hybrid':'rrf'}[run.strategy]
        def build_item(chunk_id,score,rank,score_kind):
            chunk=by_id.get(chunk_id)
            if chunk is None:return None
            dense=branch_maps.get('dense',{}).get(chunk_id,{})
            bm25=branch_maps.get('bm25',{}).get(chunk_id,{})
            return RetrievalItem(rank=rank,chunk_id=chunk.id,document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,document_name=chunk.document_name,
                content=chunk.content,page_number=chunk.page_number,ordinal=chunk.ordinal,score=score,
                score_kind=score_kind,dense_rank=dense.get('rank'),bm25_rank=bm25.get('rank'),
                dense_score=dense.get('score'),bm25_score=bm25.get('score'),fusion_rank=rank if score_kind=='rrf' else None,
                **{name:getattr(chunk,name,None) for name in ('source_block_id','char_start','char_end','content_hash','token_count')})
        items=[item for rank,(cid,score) in enumerate(zip(run.chunk_ids,run.scores),1)
            if (item:=build_item(cid,score,rank,kind)) is not None]
        branches={name:[item for saved in values[:run.top_k]
            if (item:=build_item(UUID(saved['chunk_id']),saved['score'],saved['rank'],'cosine' if name=='dense' else 'bm25')) is not None]
            for name,values in saved_branches.items()}
        return cls(run_id=run.id,space_id=run.scope.space_id,question=run.question,top_k=run.top_k,
            access_revision=run.scope.access_revision,knowledge_revision=run.scope.knowledge_revision,
            model_name=run.model_name,created_at=run.created_at,timings_ms=run.timings_ms,items=items,
            unavailable_chunk_ids=[x for x in run.chunk_ids if x not in by_id],strategy=run.strategy,
            score_kind=kind,config_snapshot=run.config_snapshot,branches=branches)



class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_number: int
    status: str
    parser_version: str
    embedding_model: str
    embedding_dimension: int
    created_at: datetime


class OwnerDocumentResponse(BaseModel):
    document: DocumentResponse
    versions: list[DocumentVersionResponse]
    chunks: list[RetrievalItem]


def get_service(request: Request, session: Annotated[AsyncSession, Depends(get_database_session, scope='function')]):
    return request.app.state.retrieval_service_factory(session)


class SavedEvidenceResponse(BaseModel):
    items: list[RetrievalItem]
    unavailable_chunk_ids: list[UUID]
    snapshot_available: bool


@router.get('/owner/eval-runs/{run_id}/results/{result_id}/evidence', response_model=SavedEvidenceResponse)
async def get_eval_evidence(run_id: UUID, result_id: UUID, user: Annotated[User, Depends(get_current_user)],
    service=Depends(get_service), evaluation=Depends(get_evaluation_service)):
    try:
        detail = await evaluation.get_run(run_id, owner_user_id=user.id)
        result = next((item for item in detail.results if item.id == result_id), None)
        if result is None:
            raise AppError(code='EVAL_RESULT_NOT_FOUND', message='评测结果不存在。', status_code=404)
        snapshot = result.execution_snapshot or {}
        candidates = snapshot.get('retrieved_chunks', [])
        chunk_ids = tuple(UUID(item['chunk_id']) for item in candidates)
        current, unavailable = await service.read_saved_evidence(space_id=detail.run.space_id, user_id=user.id, chunk_ids=chunk_ids)
    except RetrievalError as exc:
        raise AppError(code=exc.code, message=str(exc), status_code=exc.status_code) from exc
    except Exception as error:
        _translate_evaluation_error(error)
        raise
    by_id = {item.id: item for item in current}
    items = []
    for saved in candidates:
        item = by_id.get(UUID(saved['chunk_id']))
        if item is None:
            continue
        items.append(RetrievalItem(rank=saved['rank'], score=saved['score'], score_kind=saved.get('score_kind','cosine'), chunk_id=item.id,
            document_id=item.document_id, document_version_id=item.document_version_id, document_name=item.document_name,
            content=item.content, page_number=item.page_number, ordinal=item.ordinal,
            **{name: getattr(item, name, None) for name in ('source_block_id', 'char_start', 'char_end', 'content_hash', 'token_count')}))
    return SavedEvidenceResponse(items=items, unavailable_chunk_ids=list(unavailable), snapshot_available='retrieved_chunks' in snapshot)


@router.get('/owner/spaces/{space_id}/documents/{document_id}', response_model=OwnerDocumentResponse)
async def get_document_detail(space_id: UUID, document_id: UUID, user: Annotated[User, Depends(get_current_user)], service=Depends(get_service)):
    try:
        detail = await service.get_document_detail(space_id=space_id, document_id=document_id, user_id=user.id)
    except RetrievalError as exc:
        raise AppError(code=exc.code, message=str(exc), status_code=exc.status_code) from exc
    return OwnerDocumentResponse(document=DocumentResponse.model_validate(detail['document'], from_attributes=True),
        versions=[DocumentVersionResponse.model_validate(item) for item in detail['versions']],
        chunks=[RetrievalItem(rank=index, chunk_id=item.id, document_id=item.document_id,
            document_version_id=item.document_version_id, document_name=item.document_name, content=item.content,
            page_number=item.page_number, ordinal=item.ordinal, score=item.score,
            **{name: getattr(item, name, None) for name in ('source_block_id', 'char_start', 'char_end', 'content_hash', 'token_count')})
            for index, item in enumerate(detail['chunks'], 1)])


@router.post('/owner/spaces/{space_id}/retrieval-runs', response_model=RetrievalResponse, status_code=201)
async def search(space_id: UUID, payload: RetrievalRequest, user: Annotated[User, Depends(get_current_user)], service=Depends(get_service)):
    try:
        run, result = await service.search(space_id=space_id, user_id=user.id, question=payload.question, top_k=payload.top_k,strategy=payload.strategy)
    except RetrievalError as exc:
        raise AppError(code=exc.code, message=str(exc), status_code=exc.status_code) from exc
    return RetrievalResponse.build(run, [*result.items,*[item for items in result.branches.values() for item in items]])


@router.get('/owner/retrieval-runs/{run_id}', response_model=RetrievalResponse)
async def get_run(run_id: UUID, user: Annotated[User, Depends(get_current_user)], service=Depends(get_service)):
    try:
        run, chunks = await service.get_run(run_id, user_id=user.id)
    except RetrievalError as exc:
        raise AppError(code=exc.code, message=str(exc), status_code=exc.status_code) from exc
    return RetrievalResponse.build(run, chunks)
