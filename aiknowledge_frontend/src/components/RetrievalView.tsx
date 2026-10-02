import { useEffect, useRef, useState } from 'react'
import { searchKnowledge, ApiRequestError, type RetrievalItem, type RetrievalRun } from '../api/client'
import { V2Button, V2Heading, V2Notice, V2Panel } from './V2UI'
import './v2.scss'

export function RetrievalView({ spaceId, initialQuestion = '', onAsk }: {
  spaceId: string; initialQuestion?: string; onAsk: (question: string) => void
}) {
  const [question, setQuestion] = useState(initialQuestion)
  const [topK, setTopK] = useState(5)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<RetrievalRun | null>(null)
  const [selected, setSelected] = useState<RetrievalItem | null>(null)
  const controller = useRef<AbortController | null>(null)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => () => controller.current?.abort(), [spaceId])

  const search = async () => {
    if (!question.trim()) { setError('请输入问题后再开始检索。'); field.current?.focus(); return }
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setBusy(true); setError(''); setResult(null); setSelected(null)
    try {
      const run = await searchKnowledge(spaceId, question.trim(), topK, current.signal)
      if (current.signal.aborted || controller.current !== current) return
      setResult(run); setSelected(run.items[0] || null)
    } catch (failure) {
      if (!current.signal.aborted) setError(failure instanceof ApiRequestError ? failure.message : '检索暂时不可用，请稍后重试。')
    } finally {
      if (!current.signal.aborted && controller.current === current) setBusy(false)
    }
  }

  return <div className='v2-page'>
    <V2Heading title='检索测试' description='先查看相关片段，再判断是否具备回答依据。'
      actions={<V2Button kind='outline' onClick={() => onAsk(question)}>去可信问答</V2Button>}
    />
    <div className='v2-row v2-tabs'><V2Button kind='ghost' onClick={() => onAsk(question)}>可信问答</V2Button><V2Button kind='ghost' pressed>检索测试</V2Button></div>
    <V2Panel><form noValidate className='v2-query' onSubmit={event => { event.preventDefault(); void search() }}>
      <div><label htmlFor='retrieval-question'>问题</label><input data-v2-control ref={field} id='retrieval-question' maxLength={2000} value={question}
        onChange={event => setQuestion(event.target.value)} aria-invalid={!!error} aria-describedby={error ? 'retrieval-error' : undefined}
      /></div>
      <div><label htmlFor='retrieval-k'>Top K</label><select data-v2-control id='retrieval-k' value={topK} onChange={event => setTopK(Number(event.target.value))}>
        {[3, 5, 10].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      <V2Button type='submit' icon='search' disabled={busy}>{busy ? '正在检索…' : '开始检索'}</V2Button>
    </form>{error && <p id='retrieval-error' className='v2-field-error' role='alert'>{error}</p>}</V2Panel>
    {busy && <V2Panel><p role='status'>正在查找当前空间的相关片段…</p></V2Panel>}
    {result && <>
      <div className='v2-row v2-between'><strong>相关片段 · {result.items.length} 条</strong><small>仅检索当前空间 · 耗时 {Math.round(result.timings_ms.total)} ms</small></div>
      {result.items.length === 0 ? <V2Panel className='v2-empty'><h2>没有找到可用资料</h2><p>可以换个问法，或上传与问题相关的资料后重试。</p></V2Panel> :
        <div className='v2-two'><div>{result.items.map(item => <button data-native-button key={item.chunk_id} type='button' className={`v2-evidence ${selected?.chunk_id === item.chunk_id ? 'is-selected' : ''}`}
          onClick={() => setSelected(item)} aria-pressed={selected?.chunk_id === item.chunk_id}
        >
          <div className='v2-row'><span className='v2-rank'>{item.rank}</span><strong>{item.document_name}</strong></div>
          <p>{item.content}</p><small>{item.page_number ? `第 ${item.page_number} 页 · ` : ''}片段 {item.ordinal} · 相似度 {item.score.toFixed(3)}</small>
        </button>)}</div>
        {selected && <V2Panel><h2>片段 {selected.rank} · 来源定位</h2><p>{selected.document_name}</p>
          <small>{selected.page_number ? `第 ${selected.page_number} 页 · ` : ''}片段 {selected.ordinal}</small><hr /><p className='v2-source-text'>{selected.content}</p><hr />
          <V2Notice>相似度是排序依据，不是回答正确概率。</V2Notice>
          <V2Button kind='outline' onClick={() => onAsk(result.question)}>用此问题去问答</V2Button>
        </V2Panel>}</div>}
    </>}
  </div>
}
