import { useEffect, useRef, useState } from 'react'
import { ApiRequestError, previewDocumentChunks, rebuildDocumentChunks, type ChunkOptions, type ChunkPreview, type PreviewChunk } from '../api/client'
import { V2Button, V2Heading, V2Notice, V2Panel } from './V2UI'
import { ConfirmDialog } from './ConfirmDialog'
import './v2.scss'

export function ChunkPreviewView({ spaceId, documentId, filename, onBack, onRebuilt }: {
  spaceId: string; documentId: string; filename: string; onBack: () => void; onRebuilt: (enqueued: boolean) => void
}) {
  const [options, setOptions] = useState<ChunkOptions>({ strategy: 'structure', max_tokens: 512, overlap_characters: 240 })
  const [result, setResult] = useState<ChunkPreview | null>(null)
  const [selected, setSelected] = useState<{ side: string; item: PreviewChunk } | null>(null)
  const [busy, setBusy] = useState(false)
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')
  const [confirm, setConfirm] = useState(false)
  const version = useRef(0)
  const request = useRef<AbortController | null>(null)
  const alive = useRef(true)
  const mutation = useRef(false)
  useEffect(() => { const generation = version; alive.current = true; return () => { alive.current = false; generation.current++; request.current?.abort() } }, [])
  const reset = () => { version.current++; request.current?.abort(); setBusy(false); setResult(null); setSelected(null); setError('') }
  const change = (next: ChunkOptions) => { reset(); setOptions(next) }
  const load = async (offset = 0) => {
    request.current?.abort()
    const controller = new AbortController(); request.current = controller
    const current = ++version.current
    setBusy(true); setError(''); setResult(null); setSelected(null)
    try {
      const next = await previewDocumentChunks(spaceId, documentId, { ...options, offset, limit: 12 }, controller.signal)
      if (alive.current && version.current === current) setResult(next)
    } catch (failure) {
      if (alive.current && version.current === current && !controller.signal.aborted) setError(failure instanceof ApiRequestError ? failure.message : '分块预览暂时无法完成，请重试。')
    } finally { if (alive.current && version.current === current) setBusy(false) }
  }
  const apply = async () => {
    if (mutation.current || !result) return
    mutation.current = true; setApplying(true); setConfirm(false); setError('')
    const controller = new AbortController(); request.current = controller
    try {
      const accepted = await rebuildDocumentChunks(spaceId, documentId, { ...options, expected_version_id: result.document_version_id, fingerprint: result.fingerprint }, controller.signal)
      if (alive.current) onRebuilt(accepted.processing_enqueued)
    } catch (failure) {
      if (alive.current && !controller.signal.aborted) { setError(failure instanceof ApiRequestError ? failure.message : '分块重建暂时无法提交，请重试。'); setResult(null); setSelected(null) }
    } finally { mutation.current = false; if (alive.current) setApplying(false) }
  }
  const total = result ? Math.max(result.current_total, result.candidate_total) : 0
  const same = result && result.current_config.configuration_fingerprint === result.candidate_config.configuration_fingerprint
  return <div className='v2-page'>
    <V2Heading title='结构分块预览' description={filename} actions={<V2Button kind='outline' disabled={applying} onClick={onBack}>返回资料详情</V2Button>} />
    <V2Panel><form className='v2-chunk-controls' noValidate onSubmit={event => { event.preventDefault(); void load() }}>
      <div><label htmlFor='chunk-strategy'>对比分块方式</label><select data-v2-control id='chunk-strategy' disabled={applying} value={options.strategy} onChange={event => change({ ...options, strategy: event.target.value as ChunkOptions['strategy'] })}>
        <option value='structure'>按标题与段落分块</option><option value='legacy'>长度与句子分块</option></select></div>
      <div><label htmlFor='chunk-budget'>片段上限 · token</label><select data-v2-control id='chunk-budget' disabled={applying} value={options.max_tokens} onChange={event => change({ ...options, max_tokens: Number(event.target.value) })}>
        {[256, 384, 512].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      <div><label htmlFor='chunk-overlap'>最大重叠 · 字符</label><select data-v2-control id='chunk-overlap' disabled={applying} value={options.overlap_characters} onChange={event => change({ ...options, overlap_characters: Number(event.target.value) })}>
        {[0, 80, 160, 240].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      <V2Button type='submit' disabled={busy || applying}>{busy ? '正在生成预览…' : '生成分块对比'}</V2Button>
    </form></V2Panel>
    <V2Notice>预览不会生成向量或替换当前版本。应用后创建新版本，处理成功才切换；失败时继续使用旧版本。token 数包含模型特殊标记，实际重叠不超过片段的一半。</V2Notice>
    {busy && <p role='status'>正在读取原文件并计算分块，请稍候… <V2Button kind='ghost' onClick={reset}>取消预览</V2Button></p>}
    {applying && <p role='status'>正在提交新版本，请稍候…</p>}
    {error && <V2Notice danger>{error}<V2Button kind='outline' disabled={busy || applying} onClick={() => void load()}>重新预览</V2Button></V2Notice>}
    {!result && !busy && !error && <V2Panel><div className='v2-empty'><h2>先生成同一资料的分块对比</h2><p>查看现有片段和所选策略的真实结果，再决定是否创建新版本。</p></div></V2Panel>}
    {result && <>
      <div className='v2-two'>{([['current', '当前活动版本分块', result.current, result.current_total], ['candidate', options.strategy === 'structure' ? '按标题与段落分块' : '长度与句子分块', result.candidate, result.candidate_total]] as const).map(([side, title, chunks, count]) => <V2Panel key={side}>
        <h2>{title}</h2><p className='muted-copy'>共 {count} 个片段 · 当前展示 {chunks.length} 个</p>
        {!chunks.length && <V2Notice>当前页没有片段，可返回上一页。</V2Notice>}
        {chunks.map(item => <button data-native-button key={item.ordinal} type='button' className={`v2-evidence ${selected?.side === side && selected.item.ordinal === item.ordinal ? 'is-selected' : ''}`} onClick={() => setSelected({ side, item })}>
          <strong className='v2-source-text'>片段 {item.ordinal} · {item.heading_path.join(' / ') || '未提供章节'}</strong>
          <p className='v2-source-text'>{item.content.slice(0, 160)}{item.content.length > 160 ? '…' : ''}</p><small>第 {item.page_number ?? '—'} 页 · 记录 token {item.token_count ?? '未记录'} · 点击查看完整正文</small>
        </button>)}
      </V2Panel>)}</div>
      <div className='v2-row'><V2Button kind='outline' disabled={busy || applying || result.offset === 0} onClick={() => void load(Math.max(0, result.offset - result.limit))}>上一页片段</V2Button>
        <span>第 {Math.floor(result.offset / result.limit) + 1} / {Math.max(1, Math.ceil(total / result.limit))} 页</span>
        <V2Button kind='outline' disabled={busy || applying || result.offset + result.limit >= total} onClick={() => void load(result.offset + result.limit)}>下一页片段</V2Button></div>
      {selected && <V2Panel><h2>完整片段与原文定位</h2><p className='v2-source-text'>{selected.item.content}</p>
        <small>源块 {selected.item.source_block_id ?? '未记录'} · 原文区间 {selected.item.char_start ?? '—'} — {selected.item.char_end ?? '—'} · 第 {selected.item.page_number ?? '—'} 页</small></V2Panel>}
      <V2Panel><details><summary>查看本次配置记录</summary><p>当前：{String(result.current_config.strategy_version || '未记录')} · 对比：{String(result.candidate_config.strategy_version)}</p>
        <p className='v2-source-text'>模型：{result.embedding_model}</p><p className='v2-source-text'>源文件 SHA256：{result.source_sha256}</p><p className='v2-source-text'>配置指纹：{String(result.candidate_config.configuration_fingerprint)}</p></details>
        {same && <V2Notice>当前版本已采用此配置，无需重复重建。</V2Notice>}
        <V2Button disabled={busy || applying || !!same} onClick={() => setConfirm(true)}>应用分块并重建</V2Button></V2Panel>
    </>}
    {confirm && <ConfirmDialog title='创建新的分块版本？' description='将按本次预览配置重新生成向量。新版本成功后替换当前活动版本；失败保留旧版本。历史引用和评测需按新版本重新核对。' action='确认创建新版本' onCancel={() => setConfirm(false)} onConfirm={() => void apply()} />}
  </div>
}
