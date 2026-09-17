import Taro from '@tarojs/taro'

export type SpaceVisibility = 'PRIVATE' | 'PUBLIC'
export type Space = {
  id: string
  name: string
  description: string | null
  visibility: SpaceVisibility
  guest_feedback_enabled: boolean
  created_at: string
  updated_at: string
}

export type Category = {
  id: string
  space_id: string
  name: string
  description: string | null
  is_open: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export type DocumentStatus = 'PENDING' | 'PROCESSING' | 'READY' | 'FAILED' | 'DELETED'
export type KnowledgeDocument = {
  id: string
  space_id: string
  category_id: string | null
  original_filename: string
  mime_type: string
  size_bytes: number
  status: DocumentStatus
  active_version_id: string | null
  failure_code: string | null
  failure_message: string | null
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
  categories: Array<{ name: string; description: string | null }>
}

export type ShareLink = {
  id: string
  space_id: string
  category_ids: string[]
  status: string
  created_at: string
  revoked_at: string | null
  expires_at: string | null
}

export type CreatedShareLink = { link: ShareLink; token: string }

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
  id: string
  message_id: string
  rating: FeedbackRating
  reason: FeedbackReason | null
  comment: string | null
  is_guest: boolean
  created_at: string
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
}

export type EvalResult = {
  id: string
  eval_case_id: string
  answer_status: string
  answer: string
  citation_count: number
  reviewer_score: number | null
  reviewer_note: string | null
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
  }
}

type ApiOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  data?: unknown
  headers?: Record<string, string>
}

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
  try {
    const response = await Taro.request<T>({
      url: urlFor(path),
      method: options.method ?? 'GET',
      data: options.data,
      header: {
        'content-type': 'application/json',
        ...(options.headers ?? {})
      },
      credentials: 'include'
    } as Parameters<typeof Taro.request<T>>[0])
    if (response.statusCode >= 400) throw readError(response.data, response.statusCode)
    return response.data
  } catch (error) {
    if (error instanceof ApiRequestError) throw error
    throw new ApiRequestError('网络连接失败，请确认后端服务已启动。', 0)
  }
}

export async function listSpaces(): Promise<Space[]> {
  const result = await requestJson<{ items: Space[] }>('/spaces')
  return result.items
}

export async function createSpace(input: {
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
}>): Promise<Category> {
  return requestJson<Category>(`/categories/${categoryId}`, { method: 'PATCH', data: input })
}

export async function listShareLinks(spaceId: string): Promise<ShareLink[]> {
  const result = await requestJson<{ items: ShareLink[] }>(`/spaces/${spaceId}/share-links`)
  return result.items
}

export async function createShareLink(spaceId: string, categoryIds: string[]): Promise<CreatedShareLink> {
  return requestJson<CreatedShareLink>(`/spaces/${spaceId}/share-links`, {
    method: 'POST',
    data: { category_ids: categoryIds }
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

export async function uploadDocument(
  spaceId: string,
  file: UploadFile,
  categoryId: string | null,
  onProgress?: (progress: number) => void
): Promise<{ document: KnowledgeDocument; version_id: string; processing_enqueued: boolean }> {
  const isBrowserFile = typeof File !== 'undefined' && file instanceof File
  if (process.env.TARO_ENV === 'h5' && isBrowserFile && typeof XMLHttpRequest !== 'undefined') {
    return new Promise((resolve, reject) => {
      const request = new XMLHttpRequest()
      const body = new FormData()
      body.append('file', file, file.name)
      if (categoryId) body.append('category_id', categoryId)
      request.open('POST', urlFor(`/spaces/${spaceId}/documents`))
      request.withCredentials = true
      request.responseType = 'json'
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100))
      }
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) {
          resolve(request.response as { document: KnowledgeDocument; version_id: string; processing_enqueued: boolean })
        } else {
          reject(readError(request.response, request.status))
        }
      }
      request.onerror = () => reject(new ApiRequestError('上传失败，请检查网络后重试。', 0))
      request.onabort = () => reject(new ApiRequestError('上传已取消。', 0))
      request.send(body)
    })
  }

  if (!("path" in file)) {
    throw new ApiRequestError("当前平台无法读取所选文件，请重新选择。", 0)
  }
  const task = Taro.uploadFile({
    url: urlFor(`/spaces/${spaceId}/documents`),
    filePath: file.path,
    fileName: file.name,
    name: 'file',
    formData: categoryId ? { category_id: categoryId } : {},
    withCredentials: true
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

export async function askOwner(conversationId: string, question: string): Promise<OwnerAnswer> {
  return requestJson<OwnerAnswer>(`/owner/conversations/${conversationId}/messages`, {
    method: 'POST',
    data: { question, stream: false }
  })
}

async function streamAnswer<T extends OwnerAnswer | PublicAnswer>(
  path: string,
  question: string,
  onText: (text: string) => void,
  signal?: AbortSignal
): Promise<T> {
  if (typeof fetch === 'undefined' || typeof ReadableStream === 'undefined') {
    const data = await requestJson<T>(path, { method: 'POST', data: { question, stream: false } })
    onText(data.answer)
    return data
  }
  const response = await fetch(urlFor(path), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    credentials: 'include',
    signal,
    body: JSON.stringify({ question, stream: true })
  })
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
  if (!response.body || typeof response.body.getReader !== 'function') {
    // Some mini-program WebViews expose fetch but not a readable response
    // stream. Re-issue the request in JSON mode so the mobile path remains
    // usable instead of trying to parse an SSE document as JSON.
    const data = await requestJson<T>(path, { method: 'POST', data: { question, stream: false } })
    onText(data.answer)
    return data
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let answer: T | null = null
  let streamedText = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
    const events = buffer.split(/\n\n/)
    buffer = done ? '' : (events.pop() ?? '')
    for (const event of events) {
      const dataLine = event.split('\n').find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      const eventName = event.split('\n').find((line) => line.startsWith('event:'))?.slice(6).trim() ?? ''
      const payload = dataLine.slice(5).trim()
      if (!payload || payload === '[DONE]') continue
      try {
        const parsed = JSON.parse(payload) as T & { text?: unknown }
        if (eventName === 'delta' && typeof parsed.text === 'string') {
          streamedText += parsed.text
          onText(streamedText)
        } else if (typeof parsed.answer === 'string') {
          answer = parsed
          streamedText = parsed.answer
          onText(parsed.answer)
        }
      } catch {
        // The server may split an SSE event across network chunks; keep reading.
      }
    }
    if (done) break
  }
  if (!answer) throw new ApiRequestError('回答流意外结束，请重试。', 502)
  return answer
}

export async function streamOwnerAnswer(
  conversationId: string,
  question: string,
  onText: (text: string) => void,
  signal?: AbortSignal
): Promise<OwnerAnswer> {
  return streamAnswer<OwnerAnswer>(`/owner/conversations/${conversationId}/messages`, question, onText, signal)
}

export async function createPublicSession(token: string): Promise<PublicSpace> {
  return requestJson<PublicSpace>('/public/session', { method: 'POST', data: { token } })
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

export async function listFeedback(spaceId: string): Promise<Feedback[]> {
  const result = await requestJson<{ items: Feedback[] }>(`/spaces/${spaceId}/feedback`)
  return result.items
}

export async function listEvalCases(spaceId: string): Promise<EvalCase[]> {
  const result = await requestJson<{ items: EvalCase[] }>(`/spaces/${spaceId}/eval-cases`)
  return result.items
}

export async function runEvaluation(spaceId: string): Promise<EvalDetail> {
  return requestJson<EvalDetail>(`/spaces/${spaceId}/eval-runs`, { method: 'POST' })
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
