from typing import Annotated,Literal
from uuid import UUID
from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dependencies import get_current_user,get_database_session
from app.api.v1.documents import DocumentSubmissionResponse,_translate_document_error
from app.core.errors import AppError
from app.domain.retrieval import RetrievalError
from app.domain.users import User
from app.services.chunk_plan import ChunkConfig

router=APIRouter(tags=['document-chunking'])

class ChunkSettings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    strategy: Literal['legacy','structure']='structure'
    max_tokens: int=Field(default=512,ge=16,le=512,strict=True)
    overlap_characters: int=Field(default=240,ge=0,le=240,strict=True)
    def config(self):return ChunkConfig(self.strategy,self.max_tokens,self.overlap_characters)

class PreviewRequest(ChunkSettings):
    offset: int=Field(default=0,ge=0,strict=True)
    limit: int=Field(default=12,ge=1,le=50,strict=True)

class RechunkRequest(ChunkSettings):
    expected_version_id: UUID
    fingerprint: str=Field(pattern=r'^[0-9a-f]{64}$')

class PreviewChunk(BaseModel):
    ordinal: int
    content: str
    heading_path: list[str]
    page_number: int|None
    source_block_id: str|None
    char_start: int|None
    char_end: int|None
    content_hash: str|None
    token_count: int|None

class PreviewResponse(BaseModel):
    document_id: UUID
    document_version_id: UUID
    source_sha256: str
    fingerprint: str
    embedding_model: str
    current_config: dict
    candidate_config: dict
    current_total: int
    candidate_total: int
    offset: int
    limit: int
    current: list[PreviewChunk]
    candidate: list[PreviewChunk]

def service(request:Request,session:Annotated[AsyncSession,Depends(get_database_session,scope='function')]):
    return request.app.state.chunking_service_factory(session)

def translate(exc):
    if isinstance(exc,RetrievalError):raise AppError(code=exc.code,message=str(exc),status_code=exc.status_code) from exc
    _translate_document_error(exc)

@router.post('/owner/spaces/{space_id}/documents/{document_id}/chunk-preview',response_model=PreviewResponse)
async def preview(space_id:UUID,document_id:UUID,payload:PreviewRequest,user:Annotated[User,Depends(get_current_user)],svc=Depends(service)):
    try:return await svc.preview(space_id=space_id,document_id=document_id,user_id=user.id,config=payload.config(),offset=payload.offset,limit=payload.limit)
    except Exception as exc:translate(exc);raise

@router.post('/owner/spaces/{space_id}/documents/{document_id}/rechunk',response_model=DocumentSubmissionResponse,status_code=202)
async def rebuild(space_id:UUID,document_id:UUID,payload:RechunkRequest,user:Annotated[User,Depends(get_current_user)],svc=Depends(service)):
    try:return DocumentSubmissionResponse.from_domain(await svc.rebuild(space_id=space_id,document_id=document_id,user_id=user.id,
        config=payload.config(),expected_version_id=payload.expected_version_id,fingerprint=payload.fingerprint))
    except Exception as exc:translate(exc);raise
