import Taro from '@tarojs/taro'

export type SpaceVisibility = 'PRIVATE' | 'PUBLIC'
export type SpaceKind = 'PERSONAL' | 'TEAM'
export type SpacePlan = 'FREE' | 'PRO' | 'TEAM'
export type Space = {
  id: string
  owner_user_id?: string | null
  name: string
  description: string | null
  visibility: SpaceVisibility
  guest_feedback_enabled: boolean
  kind?: SpaceKind
  plan?: SpacePlan
  created_at: string
  updated_at: string
}

export type Category = {
  id: string
  space_id: string
  name: string
  description: string | null
  display_name?: string | null
  display_description?: string | null
  is_open: boolean
  sort_order: number
  is_default?: boolean
  created_at: string
  updated_at: string
}

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED' | 'DELETED'
export type KnowledgeDocument = {
  id: string
  space_id: string
  owner_user_id?: string | null
  category_id: string | null
  original_filename: string
  mime_type: string
  size_bytes: number
  status: DocumentStatus
  active_version_id: string | null
  failure_code: string | null
  failure_message: string | null
  is_enabled?: boolean
  effective_at?: string | null
  expires_at?: string | null
  created_at: string
  updated_at: string
}

export type UploadFile = File | {
  name: string
  size: number
  path: string
  type?: string
}

export type Conversation = {
  id: string
  space_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export type ConversationSummary = Conversation

export type Citation = {
  source_available?: boolean
  document_name: string
  quoted_text: string
  page_number: number | null
  ordinal: number
  score: number
}

export type AnswerStatus = 'ANSWERED' | 'INSUFFICIENT_EVIDENCE' | 'OUT_OF_SCOPE' | 'CONFLICT' | 'FAILED'
export type OwnerAnswer = {
  message_id: string
  status: AnswerStatus
  answer: string
  model: string | null
  citations: Citation[]
}

export type HistoryMessage = {
  id: string
  role: 'USER' | 'ASSISTANT' | string
  content: string
  status: AnswerStatus | null
  model: string | null
  created_at: string
  citations: Citation[]
}

export type ConversationDetail = {
  conversation: Conversation
  messages: HistoryMessage[]
}

export type PublicSpace = {
  name: string
  description: string | null
  categories: Array<{ name: string; description: string | null; display_name?: string | null; display_description?: string | null; is_default?: boolean }>
}

export type ShareLink = {
  id: string
  space_id: string
  category_ids: string[]
  status: string
  created_at: string
  revoked_at: string | null
  expires_at: string | null
  visitor_question_limit?: number | null
  allowed_origins?: string[]
}

export type CreatedShareLink = { link: ShareLink; token: string }

export type PublicQuestionRecord = {
  id: string
  share_link_id: string
  visitor_id: string
  conversation_id: string | null
  question_hash: string
  created_at: string
  is_hidden: boolean
  moderation_note: string | null
  moderated_at: string | null
}

export type PublicAnalyticsDay = {
  date: string
  sessions: number
  conversations: number
  questions: number
  unique_visitors: number
}

export type PublicAnalytics = {
  space_id: string
  period_start: string
  period_end: string
  sessions: number
  conversations: number
  questions: number
  unique_visitors: number
  daily: PublicAnalyticsDay[]
  answer_count?: number
  failed_answers?: number
  latency_p50_ms?: number | null
  latency_p95_ms?: number | null
  input_tokens?: number
  output_tokens?: number
  estimated_cost?: number
}

export type PublicAnswer = {
  message_id: string
  status: AnswerStatus
  answer: string
}

export type FeedbackRating = 'UP' | 'DOWN' | 'NEEDS_CORRECTION'
export type FeedbackReason =
  | 'OFF_TOPIC'
  | 'SOURCE_MISMATCH'
  | 'OUTDATED'
  | 'INCOMPLETE'
  | 'MISSING_MATERIAL'
export type Feedback = {
  question?: string | null
  original_answer?: string | null
  id: string
  message_id: string
  rating: FeedbackRating
  reason: FeedbackReason | null
  comment: string | null
  is_guest: boolean
  created_at: string
  review_status?: 'PENDING' | 'FIXED' | 'DEFERRED'
  corrected_answer?: string | null
  review_note?: string | null
  reviewed_at?: string | null
  data_usage_scope?: string
  pii_status?: string
}

export type KnowledgeTag = {
  id: string
  space_id: string
  name: string
  color: string | null
  created_at: string
  updated_at: string
}

export type RetrievalMetadataFilter = {
  category_ids: string[]
  tag_ids: string[]
  formats: Array<'pdf' | 'docx' | 'markdown' | 'text' | 'table' | 'presentation'>
  version_min?: number
  version_max?: number
  valid_from?: string
  valid_to?: string
}

export const emptyRetrievalMetadataFilter = (): RetrievalMetadataFilter => ({ category_ids: [], tag_ids: [], formats: [] })

export type SpaceMember = {
  user_id: string
  email: string
  display_name: string
  role: 'OWNER' | 'ADMIN' | 'EDITOR' | 'MEMBER'
  created_at: string
}

export type SpaceUsage = {
  space_id: string
  plan: SpacePlan
  documents_used: number
  documents_remaining: number
  members_used: number
  members_remaining: number
  questions_used_today: number
  questions_remaining_today: number
  limits: { documents: number; members: number; questions_per_day: number }
}

export type SourceKind = 'WEBPAGE' | 'MARKDOWN_REPOSITORY' | 'FAQ_TABLE'
export type SourceStatus = 'ACTIVE' | 'SYNCING' | 'READY' | 'FAILED' | 'DISABLED'
export type KnowledgeSource = {
  id: string
  space_id: string
  kind: SourceKind
  locator: string
  name: string | null
  status: SourceStatus
  last_checksum: string | null
  last_synced_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}
export type SourceSyncResult = {
  source: KnowledgeSource
  uploaded: number
  failed: number
  skipped: boolean
}

export type EvalCase = {
  id: string
  space_id: string
  question: string
  expected_answer: string | null
  expected_document_ids: string[]
  scope: 'OWNER' | 'PUBLIC' | 'OUT_OF_SCOPE'
  category_ids: string[]
  created_at: string
  answerable?: boolean | null
  expected_behavior?: string | null
  evidence_refs?: EvidenceRef[]
}

export type EvalSetVersion = {
  id: string
  space_id: string
  version_number: number
  label: string
  cases: EvalCase[]
  created_at: string
}

export type EvalResult = {
  id: string
  eval_case_id: string
  answer_status: string
  answer: string
  citation_count: number
  reviewer_score: number | null
  reviewer_note: string | null
  execution_snapshot?: Record<string, unknown> | null
  retrieval_metrics?: Record<string, number | boolean | null> | null
  failure_code?: string | null
}

export type EvalDetail = {
  run: {
    id: string
    space_id: string
    status: string
    retrieval_config_snapshot: Record<string, unknown>
    started_at: string | null
    completed_at: string | null
    failure_message: string | null
    created_at: string
    progress_total?: number
    progress_completed?: number
    heartbeat_at?: string | null
    task_id?: string | null
    failure_code?: string | null
  }
  results: EvalResult[]
  summary: {
    total: number
    answered: number
    insufficient_evidence: number
    out_of_scope: number
    failed: number
    citation_count: number
    out_of_scope_violations: number
    reviewed_correct: number
    reviewed_partial: number
    reviewed_incorrect: number
    answered_rate: number
    citation_rate: number
    reviewed_accuracy: number | null
    answer_accuracy?: number | null
    reviewed_coverage?: number | null
    retrieval_measured_count?: number
    document_recall_at_k?: number | null
    document_hit_at_k?: number | null
    evidence_recall_at_k?: number | null
    evidence_overlap_at_k?: number | null
    correct_refusal_rate?: number | null
  }
}

export type EvalRun = EvalDetail['run']
export type EvalRunComparison = {
  baseline: EvalRun
  candidate: EvalRun
  baseline_summary: EvalDetail['summary']
  candidate_summary: EvalDetail['summary']
  delta: Record<string, number | null>
  same_test_set: boolean
  question_changes: Array<{ eval_case_id: string; baseline_question: string | null; candidate_question: string | null;
    comparable: boolean; baseline_status: string | null; candidate_status: string | null; baseline_score: number | null; candidate_score: number | null }>
}

type ApiOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  data?: unknown
  headers?: Record<string, string>
  skipAuthRefresh?: boolean
  signal?: AbortSignal
  timeoutMs?: number
}

export type AuthUser = {
  id: string
  email: string
  display_name: string
  status: string
  created_at: string
  updated_at: string
}

export type AuthTokens = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type AuthResponse = { user: AuthUser; tokens: AuthTokens }

export type AuthSession = AuthResponse

export class ApiRequestError extends Error {
  status: number
  code: string | null

  constructor(message: string, status: number, code: string | null = null) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

const apiBase = (() => {
  const configured = process.env.TARO_APP_API_BASE
  if (configured) return configured.replace(/\/$/, '')
  return '/api/v1'
})()

const urlFor = (path: string) => `${apiBase}${path.startsWith('/') ? path : `/${path}`}`

const authStorageKey = 'aiknowledge.auth.session'
let authSession: AuthSession | null | undefined
let rememberAuthSession = false
let refreshPromise: Promise<boolean> | null = null

function readAuthSession(): AuthSession | null {
  if (authSession !== undefined) return authSession
  try {
    const stored = Taro.getStorageSync(authStorageKey)
    authSession = stored && typeof stored === 'object' ? stored as AuthSession : null
    rememberAuthSession = authSession !== null
  } catch {
    authSession = null
  }
  return authSession
}

export function getAuthUserId(): string | null {
  return readAuthSession()?.user.id || null
}

export function saveAuthSession(session: AuthSession, remember = true): void {
  authSession = session
  rememberAuthSession = remember
  refreshPromise = null
  try {
    if (remember) Taro.setStorageSync(authStorageKey, session)
    else Taro.removeStorageSync(authStorageKey)
  } catch {
    // The in-memory session keeps the current page usable when storage is unavailable.
  }
}

export function clearAuthSession(): void {
  authSession = null
  rememberAuthSession = false
  refreshPromise = null
  try { Taro.removeStorageSync(authStorageKey) } catch { /* optional storage */ }
}

function authorizationHeader(): Record<string, string> {
  const token = readAuthSession()?.tokens.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function refreshAccessToken(): Promise<boolean> {
  const current = readAuthSession()
  if (!current?.tokens.refresh_token) return false
  if (refreshPromise) return refreshPromise
  const remember = rememberAuthSession
  const pending = (async () => {
    try {
      const response = await Taro.request<AuthResponse>({
        url: urlFor('/auth/refresh'),
        cache: 'reload',
        method: 'POST',
        data: { refresh_token: current.tokens.refresh_token },
        header: { 'content-type': 'application/json' }
      } as Parameters<typeof Taro.request<AuthResponse>>[0])
      if (response.statusCode >= 400 || readAuthSession() !== current) return false
      saveAuthSession(response.data, remember)
      return true
    } catch {
      return false
    }
  })()
  refreshPromise = pending
  try {
    return await pending
  } finally {
    if (refreshPromise === pending) refreshPromise = null
  }
}

const readError = (data: unknown, status: number) => {
  if (typeof data === 'object' && data !== null) {
    const value = data as { message?: unknown; detail?: unknown; code?: unknown }
    const message = typeof value.message === 'string'
      ? value.message
      : typeof value.detail === 'string'
        ? value.detail
        : '请求暂时无法完成，请稍后重试。'
    return new ApiRequestError(message, status, typeof value.code === 'string' ? value.code : null)
  }
  return new ApiRequestError('请求暂时无法完成，请稍后重试。', status)
}

export async function requestJson<T>(path: string, options: ApiOptions = {}): Promise<T> {
  if (options.signal?.aborted) throw new ApiRequestError('请求已取消。', 0, 'REQUEST_ABORTED')
  const isPublic = path.startsWith('/public/')
  const current = readAuthSession()
  try {
    const task = Taro.request<T>({
      url: urlFor(path),
      cache: 'reload',
      timeout: options.timeoutMs ?? 60000,
      method: options.method ?? 'GET',
      data: options.data,
      header: {
        'content-type': 'application/json',
        ...(isPublic ? {} : authorizationHeader()),
        ...(options.headers ?? {})
      },
      credentials: 'include'
    } as Parameters<typeof Taro.request<T>>[0])
    const abort = () => task.abort?.()
    options.signal?.addEventListener('abort', abort, { once: true })
    let response: Awaited<typeof task>
    try { response = await task } finally { options.signal?.removeEventListener('abort', abort) }
    if (options.signal?.aborted) throw new ApiRequestError('请求已取消。', 0, 'REQUEST_ABORTED')
    if (response.statusCode === 401 && !isPublic && !options.skipAuthRefresh && (!path.startsWith('/auth/') || path === '/auth/me')) {
      if (await refreshAccessToken()) return requestJson<T>(path, { ...options, skipAuthRefresh: true })
      if (readAuthSession() === current) clearAuthSession()
    }
    if (response.statusCode >= 400) throw readError(response.data, response.statusCode)
    return response.data
  } catch (error) {
    if (options.signal?.aborted) throw new ApiRequestError('请求已取消。', 0, 'REQUEST_ABORTED')
    if (error instanceof ApiRequestError) throw error
    const failure = error as { name?: string; errMsg?: string; message?: string } | null
    if (failure?.name === 'AbortError' || /timeout|timed.out/i.test(failure?.errMsg ?? failure?.message ?? '')) {
      throw new ApiRequestError('请求等待超时，首次加载向量模型可能较慢，请稍后重试。', 0, 'REQUEST_TIMEOUT')
    }
    throw new ApiRequestError('网络连接失败，请确认后端服务已启动。', 0)
  }
}

export async function register(input: {
  email: string
  password: string
  display_name: string
}, remember = true): Promise<AuthSession> {
  const session = await requestJson<AuthResponse>('/auth/register', { method: 'POST', data: input, skipAuthRefresh: true })
  saveAuthSession(session, remember)
  return session
}

export async function login(input: { email: string; password: string }, remember = true): Promise<AuthSession> {
  const session = await requestJson<AuthResponse>('/auth/login', { method: 'POST', data: input, skipAuthRefresh: true })
  saveAuthSession(session, remember)
  return session
}

export async function logout(): Promise<void> {
  const refreshToken = readAuthSession()?.tokens.refresh_token
  clearAuthSession()
  if (refreshToken) await requestJson<unknown>('/auth/logout', { method: 'POST', data: { refresh_token: refreshToken }, skipAuthRefresh: true })
}

export async function getMe(): Promise<AuthUser> {
  return requestJson<AuthUser>('/auth/me')
}

export async function listSpaces(): Promise<Space[]> {
  const result = await requestJson<{ items: Space[] }>('/spaces')
  return result.items
}

export async function createSpace(input: {
  kind?: SpaceKind
  name: string
  description?: string
  visibility: SpaceVisibility
  guest_feedback_enabled?: boolean
}): Promise<Space> {
  return requestJson<Space>('/spaces', { method: 'POST', data: input })
}

export async function updateSpace(spaceId: string, input: Partial<{
  name: string
  description: string
  visibility: SpaceVisibility
  guest_feedback_enabled: boolean
  plan: SpacePlan
}>): Promise<Space> {
  return requestJson<Space>(`/spaces/${spaceId}`, { method: 'PATCH', data: input })
}

export async function listCategories(spaceId: string): Promise<Category[]> {
  const result = await requestJson<{ items: Category[] }>(`/spaces/${spaceId}/categories`)
  return result.items
}

export async function createCategory(spaceId: string, input: {
  name: string
  description?: string
  is_open?: boolean
  sort_order?: number
}): Promise<Category> {
  return requestJson<Category>(`/spaces/${spaceId}/categories`, { method: 'POST', data: input })
}

export async function updateCategory(categoryId: string, input: Partial<{
  name: string
  description: string
  is_open: boolean
  sort_order: number
  display_name: string | null
  display_description: string | null
  is_default: boolean
}>): Promise<Category> {
  return requestJson<Category>(`/categories/${categoryId}`, { method: 'PATCH', data: input })
}

export async function updateDocumentAvailability(documentId: string, input: {
  is_enabled?: boolean
  effective_at?: string | null
  expires_at?: string | null
}): Promise<KnowledgeDocument> {
  return requestJson<KnowledgeDocument>(`/documents/${documentId}/availability`, { method: 'PATCH', data: input })
}

export async function listShareLinks(spaceId: string): Promise<ShareLink[]> {
  const result = await requestJson<{ items: ShareLink[] }>(`/spaces/${spaceId}/share-links`)
  return result.items
}

export async function createShareLink(spaceId: string, categoryIds: string[], options?: {
  expires_at?: string | null
  password?: string | null
  visitor_question_limit?: number | null
  allowed_origins?: string[]
}): Promise<CreatedShareLink> {
  return requestJson<CreatedShareLink>(`/spaces/${spaceId}/share-links`, {
    method: 'POST',
    data: { category_ids: categoryIds, ...(options ?? {}) }
  })
}

export async function revokeShareLink(linkId: string): Promise<void> {
  await requestJson<unknown>(`/share-links/${linkId}`, { method: 'DELETE' })
}

export async function listDocuments(spaceId: string): Promise<KnowledgeDocument[]> {
  const result = await requestJson<{ items: KnowledgeDocument[] }>(`/spaces/${spaceId}/documents`)
  return result.items
}

export async function getDocument(documentId: string): Promise<KnowledgeDocument> {
  return requestJson<KnowledgeDocument>(`/documents/${documentId}`)
}

export async function deleteDocument(documentId: string): Promise<void> {
  await requestJson<unknown>(`/documents/${documentId}`, { method: 'DELETE' })
}

export async function retryDocument(documentId: string): Promise<KnowledgeDocument> {
  const result = await requestJson<{ document: KnowledgeDocument }>(`/documents/${documentId}/retry`, { method: 'POST' })
  return result.document
}

type DocumentSubmission = { document: KnowledgeDocument; version_id: string; processing_enqueued: boolean }

export function uploadDocument(spaceId: string, file: UploadFile, categoryId: string | null, onProgress?: (progress: number) => void): Promise<DocumentSubmission> {
  return uploadDocumentAt(`/spaces/${spaceId}/documents`, file, categoryId, onProgress)
}

export function uploadDocumentVersion(documentId: string, file: File, onProgress?: (progress: number) => void, signal?: AbortSignal): Promise<DocumentSubmission> {
  return uploadDocumentAt(`/documents/${documentId}/versions`, file, null, onProgress, signal)
}

export function retryDocumentVersion(documentId: string, versionId: string): Promise<DocumentSubmission> {
  return requestJson(`/documents/${documentId}/versions/${versionId}/retry`, { method: 'POST' })
}

async function uploadDocumentAt(
  path: string,
  file: UploadFile,
  categoryId: string | null,
  onProgress?: (progress: number) => void,
  signal?: AbortSignal
): Promise<{ document: KnowledgeDocument; version_id: string; processing_enqueued: boolean }> {
  const isBrowserFile = typeof File !== 'undefined' && file instanceof File
  if (signal?.aborted) throw new ApiRequestError('上传已取消。', 0, 'REQUEST_ABORTED')
  if (process.env.TARO_ENV === 'h5' && isBrowserFile && typeof XMLHttpRequest !== 'undefined') {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest()
      const abort = () => request.abort()
      const cleanup = () => signal?.removeEventListener('abort', abort)
      signal?.addEventListener('abort', abort, { once: true })
      const body = new FormData()
      body.append('file', file, file.name)
      if (categoryId) body.append('category_id', categoryId)
      request.open('POST', urlFor(path))
      request.withCredentials = true
      const token = readAuthSession()?.tokens.access_token
      if (token) request.setRequestHeader('Authorization', `Bearer ${token}`)
      request.responseType = 'json'
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
      request.onload = () => {
        cleanup()
        if (request.status >= 200 && request.status < 300) {
          resolve(request.response as { document: KnowledgeDocument; version_id: string; processing_enqueued: boolean })
        } else {
          reject(readError(request.response, request.status))
        }
      }
      request.onerror = () => { cleanup(); reject(new ApiRequestError('上传失败，请检查网络后重试。', 0)) }
      request.onabort = () => { cleanup(); reject(new ApiRequestError('上传已取消。', 0, 'REQUEST_ABORTED')) }
      request.send(body)
    })
  }

  if (!("path" in file)) {
    throw new ApiRequestError("当前平台无法读取所选文件，请重新选择。", 0)
  }
  const task = Taro.uploadFile({
    url: urlFor(path),
    filePath: file.path,
    fileName: file.name,
    name: 'file',
    formData: categoryId ? { category_id: categoryId } : {},
    withCredentials: true,
    header: authorizationHeader()
  })
  task.progress?.((event) => onProgress?.(event.progress))
  const result = await task
  if (result.statusCode >= 400) throw readError(result.data, result.statusCode)
  return typeof result.data === 'string' ? JSON.parse(result.data) as {
    document: KnowledgeDocument
    version_id: string
    processing_enqueued: boolean
  } : result.data as { document: KnowledgeDocument; version_id: string; processing_enqueued: boolean }
}

export async function createOwnerConversation(spaceId: string, title?: string): Promise<Conversation> {
  return requestJson<Conversation>('/owner/conversations', { method: 'POST', data: { space_id: spaceId, title } })
}

export async function listOwnerConversations(spaceId: string): Promise<ConversationSummary[]> {
  return requestJson<ConversationSummary[]>(
    `/owner/conversations?space_id=${encodeURIComponent(spaceId)}`
  )
}

export async function getOwnerConversation(conversationId: string): Promise<ConversationDetail> {
  return requestJson<ConversationDetail>(`/owner/conversations/${conversationId}`)
}

export async function askOwner(conversationId: string, question: string, strategy?: 'dense' | 'hybrid' | 'hybrid_rerank', metadataFilter?: RetrievalMetadataFilter): Promise<OwnerAnswer> {
  return requestJson<OwnerAnswer>(`/owner/conversations/${conversationId}/messages`, {
    method: 'POST',
    data: { question, stream: false, ...(strategy ? { strategy } : {}), ...(metadataFilter ? { metadata_filter: metadataFilter } : {}) }
  })
}

async function streamAnswer<T extends OwnerAnswer | PublicAnswer>(
  path: string,
  question: string,
  onText: (text: string) => void,
  signal?: AbortSignal,
  skipAuthRefresh = false,
  strategy?: 'dense' | 'hybrid' | 'hybrid_rerank',
  metadataFilter?: RetrievalMetadataFilter
): Promise<T> {
  signal?.throwIfAborted()
  if (typeof fetch === 'undefined' || typeof ReadableStream === 'undefined') {
    const data = await requestJson<T>(path, { method: 'POST', data: { question, stream: false, ...(strategy ? { strategy } : {}), ...(metadataFilter && !path.startsWith('/public/') ? { metadata_filter: metadataFilter } : {}) } })
    onText(data.answer)
    return data
  }
  const isPublic = path.startsWith('/public/')
  const current = readAuthSession()
  const response = await fetch(urlFor(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...(isPublic ? {} : authorizationHeader()) },
    credentials: 'include',
    signal,
    body: JSON.stringify({ question, stream: true, ...(strategy ? { strategy } : {}), ...(metadataFilter && !isPublic ? { metadata_filter: metadataFilter } : {}) })
  })
  if (response.status === 401 && !isPublic && !skipAuthRefresh) {
    if (await refreshAccessToken()) return streamAnswer<T>(path, question, onText, signal, true, strategy, metadataFilter)
    if (readAuthSession() === current) clearAuthSession()
  }
  if (!response.ok) {
    let data: unknown = null
    try { data = await response.json() } catch { /* keep generic error */ }
    throw readError(data, response.status)
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('text/event-stream')) {
    const data = await response.json() as T
    onText(data.answer)
    return data
  }
  let answer: T | null = null
  let streamedText = ''
  const consumeEvents = (events: string[]) => {
    for (const event of events) {
      const lines = event.split(/\r?\n/)
      const eventName = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() ?? ''
      const payload = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
      if (!payload || payload === '[DONE]') continue
      try {
        const parsed = JSON.parse(payload) as T & { text?: unknown }
        if (eventName === 'error') {
          onText('')
          throw readError(parsed, 409)
        } else if (eventName === 'delta' && typeof parsed.text === 'string') {
          streamedText += parsed.text
          onText(streamedText)
        } else if (typeof parsed.answer === 'string') {
          answer = parsed
          streamedText = parsed.answer
          onText(parsed.answer)
        }
      } catch (error) {
        if (error instanceof ApiRequestError) throw error
        // Ignore malformed events; an absent final answer still fails below.
      }
    }
  }
  if (!response.body || typeof response.body.getReader !== 'function') {
    // The server has already persisted the answer. Read this response instead
    // of submitting the same question again and consuming quota twice.
    consumeEvents((await response.text()).split(/\r?\n\r?\n/))
  } else {
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
        const events = buffer.split(/\r?\n\r?\n/)
        buffer = done ? '' : (events.pop() ?? '')
        consumeEvents(events)
        if (done) break
      }
    } catch (failure) {
      await reader.cancel().catch(() => undefined)
      throw failure
    } finally {
      reader.releaseLock()
    }
  }
  if (!answer) throw new ApiRequestError('回答流意外结束，请重试。', 502)
  return answer
}

export async function streamOwnerAnswer(
  conversationId: string,
  question: string,
  onText: (text: string) => void,
  signal?: AbortSignal,
  strategy?: 'dense' | 'hybrid' | 'hybrid_rerank',
  metadataFilter?: RetrievalMetadataFilter
): Promise<OwnerAnswer> {
  return streamAnswer<OwnerAnswer>(`/owner/conversations/${conversationId}/messages`, question, onText, signal, false, strategy, metadataFilter)
}

export async function createPublicSession(token: string, password?: string): Promise<PublicSpace> {
  return requestJson<PublicSpace>('/public/session', { method: 'POST', data: { token, ...(password ? { password } : {}) } })
}

export function publicShareUrl(token: string, baseUrl = typeof window === 'undefined' ? '' : window.location.origin): string {
  return `${baseUrl.replace(/\/$/, '')}/#/pages/public/public?token=${encodeURIComponent(token)}`
}

export async function getPublicSpace(): Promise<PublicSpace> {
  return requestJson<PublicSpace>('/public/space')
}

export async function createPublicConversation(title?: string): Promise<Conversation> {
  return requestJson<Conversation>('/public/conversations', { method: 'POST', data: { title } })
}

export async function streamPublicAnswer(
  conversationId: string,
  question: string,
  onText: (text: string) => void,
  signal?: AbortSignal
): Promise<PublicAnswer> {
  return streamAnswer<PublicAnswer>(`/public/conversations/${conversationId}/messages`, question, onText, signal)
}

export async function queryPublicShare(input: { token: string; password?: string; question: string }): Promise<PublicAnswer> {
  return requestJson<PublicAnswer>('/public/query', { method: 'POST', data: input })
}

export async function sendFeedback(
  messageId: string,
  payload: { rating: FeedbackRating; reason?: FeedbackReason; comment?: string },
  isPublic = false
): Promise<Feedback> {
  return requestJson<Feedback>(`${isPublic ? '/public' : ''}/messages/${messageId}/feedback`, {
    method: 'POST',
    data: payload
  })
}

export async function listFeedback(spaceId: string, filters?: {
  review_status?: Feedback['review_status']
  rating?: FeedbackRating
  is_guest?: boolean
}): Promise<Feedback[]> {
  const query = new URLSearchParams()
  if (filters?.review_status) query.set('review_status', filters.review_status)
  if (filters?.rating) query.set('rating', filters.rating)
  if (filters?.is_guest !== undefined) query.set('is_guest', String(filters.is_guest))
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const result = await requestJson<{ items: Feedback[] }>(`/spaces/${spaceId}/feedback${suffix}`)
  return result.items
}

export async function reviewFeedback(feedbackId: string, input: {
  review_status: 'PENDING' | 'FIXED' | 'DEFERRED'
  corrected_answer?: string | null
  review_note?: string | null
  data_usage_scope?: string
  pii_status?: string
}): Promise<Feedback> {
  return requestJson<Feedback>(`/feedback/${feedbackId}`, { method: 'PATCH', data: input })
}

export async function listTags(spaceId: string): Promise<KnowledgeTag[]> {
  const result = await requestJson<{ items: KnowledgeTag[] }>(`/spaces/${spaceId}/tags`)
  return result.items
}

export async function createTag(spaceId: string, input: { name: string; color?: string | null }): Promise<KnowledgeTag> {
  return requestJson<KnowledgeTag>(`/spaces/${spaceId}/tags`, { method: 'POST', data: input })
}

export async function updateTag(tagId: string, input: { name: string; color?: string | null }): Promise<KnowledgeTag> {
  return requestJson<KnowledgeTag>(`/tags/${tagId}`, { method: 'PATCH', data: input })
}

export async function deleteTag(tagId: string): Promise<void> {
  await requestJson<unknown>(`/tags/${tagId}`, { method: 'DELETE' })
}

export async function setDocumentTags(spaceId: string, documentId: string, tagIds: string[]): Promise<KnowledgeTag[]> {
  const result = await requestJson<{ items: KnowledgeTag[] }>(`/spaces/${spaceId}/documents/${documentId}/tags`, {
    method: 'PUT', data: { tag_ids: tagIds }
  })
  return result.items
}

export async function listDocumentTags(documentId: string): Promise<KnowledgeTag[]> {
  const result = await requestJson<{ items: KnowledgeTag[] }>(`/documents/${documentId}/tags`)
  return result.items
}

export async function searchDocuments(spaceId: string, query: string, tagId?: string): Promise<KnowledgeDocument[]> {
  // The API names this filter `query`; keeping the same key here avoids a
  // silent empty-result search when the browser sends the legacy `q` key.
  const params = new URLSearchParams({ query })
  if (tagId) params.set('tag_id', tagId)
  const result = await requestJson<{ items: KnowledgeDocument[] }>(`/spaces/${spaceId}/documents/search?${params.toString()}`)
  return result.items
}

export async function listMembers(spaceId: string): Promise<SpaceMember[]> {
  return requestJson<SpaceMember[]>(`/spaces/${spaceId}/members`)
}

export async function addMember(spaceId: string, input: { email: string; role: 'ADMIN' | 'EDITOR' | 'MEMBER' }): Promise<SpaceMember> {
  return requestJson<SpaceMember>(`/spaces/${spaceId}/members`, { method: 'POST', data: input })
}

export async function changeMemberRole(spaceId: string, userId: string, role: 'ADMIN' | 'EDITOR' | 'MEMBER'): Promise<SpaceMember> {
  return requestJson<SpaceMember>(`/spaces/${spaceId}/members/${userId}`, { method: 'PATCH', data: { role } })
}

export async function removeMember(spaceId: string, userId: string): Promise<void> {
  await requestJson<unknown>(`/spaces/${spaceId}/members/${userId}`, { method: 'DELETE' })
}

export async function getSpaceUsage(spaceId: string): Promise<SpaceUsage> {
  return requestJson<SpaceUsage>(`/spaces/${spaceId}/usage`)
}

export async function listSources(spaceId: string): Promise<KnowledgeSource[]> {
  const result = await requestJson<{ items: KnowledgeSource[] }>(`/spaces/${spaceId}/sources`)
  return result.items
}

export async function createSource(spaceId: string, input: {
  kind: SourceKind
  locator: string
  name?: string | null
}): Promise<KnowledgeSource> {
  return requestJson<KnowledgeSource>(`/spaces/${spaceId}/sources`, { method: 'POST', data: input })
}

export async function setSourceStatus(sourceId: string, sourceStatus: 'ACTIVE' | 'DISABLED'): Promise<KnowledgeSource> {
  return requestJson<KnowledgeSource>(`/sources/${sourceId}`, { method: 'PATCH', data: { status: sourceStatus } })
}

export async function syncSource(sourceId: string): Promise<SourceSyncResult> {
  return requestJson<SourceSyncResult>(`/sources/${sourceId}/sync`, { method: 'POST' })
}

export async function listPublicQuestionRecords(spaceId: string): Promise<PublicQuestionRecord[]> {
  const result = await requestJson<{ items: PublicQuestionRecord[] }>(`/spaces/${spaceId}/public-questions`)
  return result.items
}

export async function getPublicAnalytics(spaceId: string, days = 30): Promise<PublicAnalytics> {
  return requestJson<PublicAnalytics>(`/spaces/${spaceId}/public-analytics?days=${days}`)
}

export async function moderatePublicQuestion(questionId: string, input: {
  is_hidden: boolean
  moderation_note?: string | null
}): Promise<PublicQuestionRecord> {
  return requestJson<PublicQuestionRecord>(`/public-questions/${questionId}`, {
    method: 'PATCH', data: input
  })
}

export async function listEvalCases(spaceId: string): Promise<EvalCase[]> {
  const result = await requestJson<{ items: EvalCase[] }>(`/spaces/${spaceId}/eval-cases`)
  return result.items
}

export async function createEvalCase(spaceId: string, input: {
  question: string
  expected_answer?: string | null
  expected_document_ids?: string[]
  scope?: EvalCase['scope']
  category_ids?: string[]
  answerable?: boolean | null
  expected_behavior?: string | null
  evidence_refs?: EvidenceRef[]
}): Promise<EvalCase> {
  return requestJson<EvalCase>(`/spaces/${spaceId}/eval-cases`, { method: 'POST', data: input })
}

export async function updateEvalCase(caseId: string, input: Partial<{
  question: string
  expected_answer: string | null
  expected_document_ids: string[]
  scope: EvalCase['scope']
  category_ids: string[]
  answerable: boolean | null
  expected_behavior: string | null
  evidence_refs: EvidenceRef[]
}>): Promise<EvalCase> {
  return requestJson<EvalCase>(`/eval-cases/${caseId}`, { method: 'PATCH', data: input })
}

export async function deleteEvalCase(caseId: string): Promise<void> {
  await requestJson<unknown>(`/eval-cases/${caseId}`, { method: 'DELETE' })
}

export async function reviewEvalResult(resultId: string, input: { reviewer_score: 0 | 0.5 | 1; reviewer_note?: string | null }): Promise<EvalResult> {
  return requestJson<EvalResult>(`/eval-results/${resultId}`, { method: 'PATCH', data: input })
}

export async function runEvaluation(spaceId: string): Promise<EvalDetail> {
  return requestJson<EvalDetail>(`/spaces/${spaceId}/eval-runs`, { method: 'POST' })
}

export async function listEvalRuns(spaceId: string, limit = 20): Promise<EvalDetail['run'][]> {
  const result = await requestJson<{ items: EvalDetail['run'][] }>(`/spaces/${spaceId}/eval-runs?limit=${limit}`)
  return result.items
}

export async function compareEvalRuns(spaceId: string, baselineRunId: string, candidateRunId: string): Promise<EvalRunComparison> {
  const params = new URLSearchParams({
    baseline_run_id: baselineRunId,
    candidate_run_id: candidateRunId
  })
  return requestJson<EvalRunComparison>(`/spaces/${spaceId}/eval-runs/compare?${params.toString()}`)
}

export async function createEvalVersion(spaceId: string, label: string): Promise<EvalSetVersion> {
  return requestJson<EvalSetVersion>(`/spaces/${spaceId}/eval-versions`, {
    method: 'POST',
    data: { label }
  })
}

export async function listEvalVersions(spaceId: string, limit = 20): Promise<EvalSetVersion[]> {
  const result = await requestJson<{ items: EvalSetVersion[] }>(`/spaces/${spaceId}/eval-versions?limit=${limit}`)
  return result.items
}

export async function runEvalVersion(versionId: string): Promise<EvalDetail> {
  return requestJson<EvalDetail>(`/eval-versions/${versionId}/runs`, { method: 'POST' })
}

export type EvidenceRef = {
  document_id: string
  document_version_id: string
  source_block_id: string
  char_start: number
  char_end: number
  text_hash: string
  required: boolean
}

export type RetrievalItem = {
  dense_rank?: number | null
  bm25_rank?: number | null
  fusion_rank?: number | null
  fusion_score?: number | null
  rerank_rank?: number | null
  rerank_score?: number | null
  dense_score?: number | null
  bm25_score?: number | null
  score_kind?: 'cosine' | 'bm25' | 'rrf' | 'cross_encoder'
  rank: number
  chunk_id: string
  document_id: string
  document_version_id: string | null
  document_name: string
  content: string
  page_number: number | null
  ordinal: number
  score: number
  source_block_id: string | null
  char_start: number | null
  char_end: number | null
  content_hash: string | null
  token_count: number | null
}

export type RetrievalRun = {
  branches?: Record<string, RetrievalItem[]>
  strategy?: 'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank'
  score_kind?: 'cosine' | 'bm25' | 'rrf' | 'cross_encoder'
  config_snapshot?: Record<string, unknown>
  status: 'COMPLETED'
  run_id: string
  space_id: string
  question: string
  top_k: number
  access_revision: number
  knowledge_revision: number
  model_name: string
  created_at: string
  timings_ms: { embedding: number; search?: number; corpus?: number; ranking?: number; total: number }
  items: RetrievalItem[]
  unavailable_chunk_ids: string[]
}

export type OwnerDocumentDetail = {
  document: KnowledgeDocument
  versions: Array<{ id: string; version_number: number; status: string; parser_version: string;
    embedding_model: string; embedding_dimension: number; created_at: string; chunk_config?: Record<string, unknown> }>
  chunks: RetrievalItem[]
}

export async function getOwnerDocumentDetail(spaceId: string, documentId: string, signal?: AbortSignal): Promise<OwnerDocumentDetail> {
  return requestJson<OwnerDocumentDetail>(`/owner/spaces/${spaceId}/documents/${documentId}`, { signal })
}

export type ChunkOptions = { strategy: 'legacy' | 'structure'; max_tokens: number; overlap_characters: number }
export type PreviewChunk = { ordinal: number; content: string; heading_path: string[]; page_number: number | null;
  source_block_id: string | null; char_start: number | null; char_end: number | null; content_hash: string | null; token_count: number | null }
export type ChunkPreview = { document_id: string; document_version_id: string; source_sha256: string; fingerprint: string;
  embedding_model: string; current_config: Record<string, unknown>; candidate_config: Record<string, unknown>;
  current_total: number; candidate_total: number; offset: number; limit: number; current: PreviewChunk[]; candidate: PreviewChunk[] }
export function previewDocumentChunks(spaceId: string, documentId: string, input: ChunkOptions & { offset?: number; limit?: number }, signal?: AbortSignal): Promise<ChunkPreview> {
  return requestJson(`/owner/spaces/${spaceId}/documents/${documentId}/chunk-preview`, { method: 'POST', data: input, signal, timeoutMs: 660000 })
}
export function rebuildDocumentChunks(spaceId: string, documentId: string, input: ChunkOptions & { expected_version_id: string; fingerprint: string }, signal?: AbortSignal): Promise<DocumentSubmission> {
  return requestJson(`/owner/spaces/${spaceId}/documents/${documentId}/rechunk`, { method: 'POST', data: input, signal })
}

export type EvalEvidence = { items: RetrievalItem[]; unavailable_chunk_ids: string[]; snapshot_available: boolean }
export function getEvalEvidence(runId: string, resultId: string, signal?: AbortSignal): Promise<EvalEvidence> {
  return requestJson(`/owner/eval-runs/${runId}/results/${resultId}/evidence`, { signal })
}

export async function searchKnowledge(spaceId: string, question: string, topK = 5, signal?: AbortSignal, strategy?: 'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank', metadataFilter?: RetrievalMetadataFilter): Promise<RetrievalRun> {
  return requestJson<RetrievalRun>(`/owner/spaces/${spaceId}/retrieval-runs`, { method: 'POST', data: { question, top_k: topK, ...(strategy ? { strategy } : {}), metadata_filter: metadataFilter || emptyRetrievalMetadataFilter() }, signal, timeoutMs: 660000 })
}

export async function getRetrievalRun(runId: string, signal?: AbortSignal): Promise<RetrievalRun> {
  return requestJson<RetrievalRun>(`/owner/retrieval-runs/${runId}`, { signal })
}

export async function enqueueEvaluation(spaceId: string, strategy?: 'dense' | 'hybrid' | 'hybrid_rerank', metadataFilter?: RetrievalMetadataFilter): Promise<EvalRun> {
  return requestJson<EvalRun>(`/spaces/${spaceId}/eval-runs/async${strategy ? `?strategy=${strategy}` : ''}`, { method: 'POST', data: { metadata_filter: metadataFilter || emptyRetrievalMetadataFilter() } })
}

export async function enqueueEvalVersion(versionId: string, strategy?: 'dense' | 'hybrid' | 'hybrid_rerank', metadataFilter?: RetrievalMetadataFilter): Promise<EvalRun> {
  return requestJson<EvalRun>(`/eval-versions/${versionId}/runs/async${strategy ? `?strategy=${strategy}` : ''}`, { method: 'POST', data: { metadata_filter: metadataFilter || emptyRetrievalMetadataFilter() } })
}

export async function getEvalRun(runId: string, signal?: AbortSignal): Promise<EvalDetail> {
  return requestJson<EvalDetail>(`/eval-runs/${runId}`, { signal })
}

export async function retryEvalRun(runId: string): Promise<EvalRun> {
  return requestJson<EvalRun>(`/eval-runs/${runId}/retry`, { method: 'POST' })
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
