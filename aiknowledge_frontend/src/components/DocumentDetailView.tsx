import { useEffect, useRef, useState } from 'react'
import { ApiRequestError, deleteDocument, formatFileSize, getOwnerDocumentDetail, retryDocumentVersion, uploadDocumentVersion, type OwnerDocumentDetail, type RetrievalItem } from '../api/client'
import { ConfirmDialog } from './ConfirmDialog'
import { ChunkPreviewView } from './ChunkPreviewView'
import { V2Button, V2Heading, V2Notice, V2Panel } from './V2UI'
import './v2.scss'

export function DocumentDetailView({ spaceId, documentId, onBack, onAsk, onRetrieve }: {
  spaceId: string; documentId: string; onBack: () => void; onAsk: () => void; onRetrieve: () => void
}) {
  const [detail, setDetail] = useState<OwnerDocumentDetail | null>(null)
  const [selected, setSelected] = useState<RetrievalItem | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const upload = useRef<AbortController | null>(null)
  const alive = useRef(true)
  const mutation = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false; upload.current?.abort() } }, [])
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    setLoading(true); setError('')
    const load = async () => {
      if (document.hidden) { timer = setTimeout(() => { void load() }, 2000); return }
      try {
        const next = await getOwnerDocumentDetail(spaceId, documentId, controller.signal)
        if (controller.signal.aborted) return
        setDetail(next); setError(''); setSelected(previous => next.chunks.find(item => item.chunk_id === previous?.chunk_id) || next.chunks[0] || null)
        failures = 0
        if (next.versions.some(version => version.status === 'PROCESSING')) timer = setTimeout(() => { void load() }, 2000)
      } catch (failure) {
        if (controller.signal.aborted) return
        setError(failure instanceof ApiRequestError ? failure.message : '资料详情暂时无法加载。')
        if (++failures < 3) timer = setTimeout(() => { void load() }, 3000)
      } finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [spaceId, documentId, attempt])
  const perform = async (action: () => Promise<void>) => {
    if (mutation.current) return
    mutation.current = true; setBusy(true); setError(''); setNotice('')
    try { await action() }
    catch (failure) { if (alive.current && !(failure instanceof ApiRequestError && failure.code === 'REQUEST_ABORTED')) setError(failure instanceof Error ? failure.message : '操作失败，请重试。') }
    finally { mutation.current = false; if (alive.current) { setBusy(false); setProgress(null) } }
  }
  const pending = detail?.versions.some(version => version.status === 'PROCESSING') || false
  if (previewing && detail) return <ChunkPreviewView spaceId={spaceId} documentId={documentId} filename={detail.document.original_filename}
    onBack={() => setPreviewing(false)} onRebuilt={enqueued => { setPreviewing(false); setNotice(enqueued ? '分块重建已提交，新版本可用前继续使用旧版本。' : '重建未入队，旧版本仍可用，请查看失败版本并重试。'); setAttempt(value => value + 1) }}
  />
  return <div className='v2-page'>
    <V2Heading title='资料详情' description={detail?.document.original_filename || '查看当前资料与版本记录。'}
      actions={<><V2Button kind='outline' onClick={onBack}>返回资料</V2Button><V2Button onClick={onAsk} disabled={detail?.document.status !== 'READY'}>开始提问</V2Button></>}
    />
    {loading && !detail && <V2Panel><p role='status'>正在加载资料与片段…</p></V2Panel>}
    {error && <V2Notice danger>{error}<V2Button kind='outline' disabled={busy} onClick={() => setAttempt(value => value+1)}>重新加载</V2Button></V2Notice>}
    {notice && <V2Notice>{notice}</V2Notice>}
    {detail && <div className='v2-two'><div>
      <V2Panel><h2>当前活动版本</h2><div className='v2-row'><strong>{detail.document.status === 'READY' ? '可用于问答' : detail.document.status === 'FAILED' ? '处理失败' : '处理中'}</strong>
        <small>{formatFileSize(detail.document.size_bytes)} · {detail.chunks.length} 个当前可用片段</small></div>
        {detail.document.failure_message && <V2Notice danger>{detail.document.failure_message}</V2Notice>}
        <p>{detail.document.original_filename}</p><div className='v2-row'><V2Button kind='outline' onClick={onRetrieve}>检索测试</V2Button>
          <V2Button kind='outline' disabled={pending || detail.document.status !== 'READY' || !detail.chunks.length} onClick={() => setPreviewing(true)}>结构分块预览</V2Button></div>
      </V2Panel>
      <V2Panel><h2>原文片段</h2>{!detail.chunks.length ? <p>当前没有可用片段，请检查处理状态、启用状态与有效时间。</p> : <>
        <div className='v2-row'>{detail.chunks.map(item => <V2Button key={item.chunk_id} kind='outline' pressed={selected?.chunk_id === item.chunk_id} onClick={() => setSelected(item)}>片段 {item.ordinal}</V2Button>)}</div>
        {selected && <><hr /><small>{selected.page_number ? '第 ' + selected.page_number + ' 页 · ' : ''}{selected.source_block_id || '旧资料位置待更新'}{selected.char_start != null ? ' · 原文区间 ' + selected.char_start + '—' + selected.char_end : ''}</small><p className='v2-source-text'>{selected.content}</p></>}
      </>}</V2Panel>
    </div><aside>
      <V2Panel><h2>版本记录</h2>{detail.versions.map(version => <div key={version.id}>
        <p><strong>v{version.version_number}</strong> · {version.id === detail.document.active_version_id ? '当前活动版本' : version.status === 'PROCESSING' ? '处理中' : version.status === 'FAILED' ? '处理失败' : '历史版本'}<br /><small>{new Date(version.created_at).toLocaleString('zh-CN')}</small></p>
        {version.status === 'FAILED' && <V2Button kind='outline' disabled={busy || pending} onClick={() => { void perform(async () => {
          const result = await retryDocumentVersion(documentId, version.id)
          if (alive.current) { setNotice(result.processing_enqueued ? '已提交重试。' : '处理队列暂不可用，请稍后重试。'); setAttempt(value => value+1) }
        }) }}
        >重试此版本</V2Button>}
      </div>)}</V2Panel>
      <V2Panel><h2>维护资料</h2><p><small>新版本处理成功后切换；处理失败时保留当前版本。</small></p>
        <input data-v2-control ref={fileInput} type='file' accept='.pdf,.txt,.md,.docx' aria-label='选择更新后的资料' hidden onChange={event => {
          const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''
          if (file) void perform(async () => {
            const controller = new AbortController(); upload.current = controller; setProgress(0)
            const result = await uploadDocumentVersion(documentId, file, value => { if (alive.current) setProgress(value) }, controller.signal)
            if (alive.current) { setNotice(result.processing_enqueued ? '新版本已提交处理，成功后自动切换当前版本。' : '新版本未能进入处理队列，请在版本记录中重试。'); setAttempt(value => value+1) }
          })
        }}
        />
        <div className='v2-row'><V2Button kind='outline' disabled={busy || pending || detail.document.status !== 'READY'} onClick={() => fileInput.current?.click()}>更新资料</V2Button><V2Button kind='danger' disabled={busy} onClick={() => setConfirmDelete(true)}>删除资料</V2Button></div>
        {progress != null && <p role='status'>上传进度 {progress}%<V2Button kind='ghost' onClick={() => upload.current?.abort()}>取消上传</V2Button></p>}
      </V2Panel>
    </aside></div>}
    {confirmDelete && <ConfirmDialog title='删除这份资料？' description='删除后，这份资料将不再用于新的检索和回答。' action='删除资料' onCancel={() => setConfirmDelete(false)} onConfirm={() => {
      setConfirmDelete(false); void perform(async () => { await deleteDocument(documentId); if (alive.current) onBack() })
    }}
    />}
  </div>
}
