import { useEffect, useRef, useState } from 'react'
import { searchKnowledge, ApiRequestError, emptyRetrievalMetadataFilter, type Category, type KnowledgeTag, type RetrievalItem, type RetrievalMetadataFilter, type RetrievalRun } from '../api/client'
import { V2Button, V2Heading, V2Notice, V2Panel } from './V2UI'
import { RetrievalMetadataFilterControls } from './RetrievalMetadataFilterControls'
import './v2.scss'

export function RetrievalView({ spaceId, initialQuestion = '', categories, tags, onAsk }: {
  spaceId: string; initialQuestion?: string; categories: Category[]; tags: KnowledgeTag[]
  onAsk: (question: string, strategy?: 'dense' | 'hybrid' | 'hybrid_rerank', metadataFilter?: RetrievalMetadataFilter) => void
}) {
  const [question, setQuestion] = useState(initialQuestion)
  const [topK, setTopK] = useState(5)
  const [strategy, setStrategy] = useState<'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank'>('dense')
  const [metadataFilter, setMetadataFilter] = useState(emptyRetrievalMetadataFilter)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<RetrievalRun | null>(null)
  const [selected, setSelected] = useState<RetrievalItem | null>(null)
  const controller = useRef<AbortController | null>(null)
  const field = useRef<HTMLInputElement>(null)
  useEffect(() => {
    controller.current?.abort(); controller.current = null
    setBusy(false); setError(''); setResult(null); setSelected(null)
    return () => controller.current?.abort()
  }, [spaceId])

  const resetResults = () => {
    controller.current?.abort(); controller.current = null
    setBusy(false); setError(''); setResult(null); setSelected(null)
  }

  const search = async () => {
    if (busy) return
    if (!question.trim()) { setError('请输入问题后再开始检索。'); field.current?.focus(); return }
    if (metadataFilter.version_min != null && metadataFilter.version_max != null && metadataFilter.version_min > metadataFilter.version_max) {
      setError('版本起始值不能大于结束值。'); return
    }
    if (metadataFilter.valid_from && metadataFilter.valid_to && Date.parse(metadataFilter.valid_from) >= Date.parse(metadataFilter.valid_to)) {
      setError('有效时间范围的开始时间必须早于结束时间。'); return
    }
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setBusy(true); setError(''); setResult(null); setSelected(null)
    try {
      const run = await searchKnowledge(spaceId, question.trim(), topK, current.signal, strategy, metadataFilter)
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
      actions={<V2Button kind='outline' onClick={() => onAsk(question,strategy==='hybrid_rerank' ? 'hybrid_rerank' : strategy==='hybrid' ? 'hybrid' : 'dense', metadataFilter)}>去可信问答</V2Button>}
    />
    <div className='v2-row v2-tabs'><V2Button kind='ghost' onClick={() => onAsk(question,strategy==='hybrid_rerank' ? 'hybrid_rerank' : strategy==='hybrid' ? 'hybrid' : 'dense', metadataFilter)}>可信问答</V2Button><V2Button kind='ghost' pressed>检索测试</V2Button></div>
    <V2Panel><form noValidate className='v2-query v2-query-strategy' onSubmit={event => { event.preventDefault(); void search() }}>
      <div><label htmlFor='retrieval-question'>问题</label><div className='v2-input-clear'><input data-v2-control ref={field} id='retrieval-question' maxLength={2000} value={question}
        onChange={event => { resetResults(); setQuestion(event.target.value) }}
        onKeyDown={event => { if (event.key === 'Enter' && event.nativeEvent.isComposing) event.preventDefault() }}
        aria-invalid={!!error} aria-describedby={error ? 'retrieval-error' : undefined}
      />{question && <button data-native-button className='v2-clear-query' type='button' aria-label='清空检索问题'
        onClick={() => { resetResults(); setQuestion(''); field.current?.focus() }}
      >×</button>}</div></div>
      <div><label htmlFor='retrieval-strategy'>检索方式</label><select data-v2-control id='retrieval-strategy' value={strategy}
        onChange={event => { resetResults(); setStrategy(event.target.value as 'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank') }}
      >
        <option value='dense'>向量检索</option><option value='bm25'>关键词检索 · BM25</option><option value='hybrid'>混合检索 · RRF</option><option value='hybrid_rerank'>混合检索 + 模型重排</option></select></div>
      <div><label htmlFor='retrieval-k'>Top K</label><select data-v2-control id='retrieval-k' value={topK} onChange={event => { resetResults(); setTopK(Number(event.target.value)) }}>
        {[3, 5, 10].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      <V2Button type='submit' icon='search' disabled={busy}>{busy ? '正在检索…' : '开始检索'}</V2Button>
    </form><RetrievalMetadataFilterControls value={metadataFilter} categories={categories} tags={tags} disabled={busy} onChange={value => { resetResults(); setMetadataFilter(value) }} />{error && <p id='retrieval-error' className='v2-field-error' role='alert'>{error}</p>}</V2Panel>
    {strategy === 'bm25' && <V2Notice>查找编号、版本号或原文关键词。当前仅用于检索测试，去问答仍沿用现有问答方式。</V2Notice>}
    {strategy === 'hybrid' && <V2Notice>对比两路实际召回与融合排名。去问答时使用本次混合检索方式；融合分数不是回答正确概率。</V2Notice>}
    {strategy==='hybrid_rerank' && <V2Notice>比较同一候选池的重排前后顺序。重排分数不是正确概率；首次加载模型可能需要较长时间。</V2Notice>}
    {busy && <V2Panel><p role='status'>正在查找当前空间的相关片段…</p></V2Panel>}
    {result && <>
      <div className='v2-row v2-between'><strong>相关片段 · {result.items.length} 条</strong><small>{result.strategy === 'hybrid_rerank' ? '模型重排' : result.strategy === 'hybrid' ? '混合检索' : result.strategy === 'bm25' ? '关键词检索' : '向量检索'} · 当前空间 · 耗时 {Math.round(result.timings_ms.total)} ms</small></div>
      {result.strategy==='hybrid_rerank' && <>
        <div className='v2-rerank-grid'>{([['before','重排前 · RRF'],['after','重排后 · 真实模型']] as const).map(([key,title])=>{
          const items=key==='before' ? result.branches?.fusion || [] : result.items
          return <V2Panel key={key}><h2>{title}</h2><small>{items.length} 条 · 同一候选池</small>
            {!items.length && <p>本路没有可用片段。</p>}
            {items.map(item=><button data-native-button type='button' key={item.chunk_id} className={`v2-evidence ${selected===item ? 'is-selected' : ''}`} onClick={()=>setSelected(item)} aria-pressed={selected===item}>
              <div className='v2-row'><span className='v2-rank'>{item.rank}</span><strong>{item.document_name}</strong></div>
              <p className='v2-rerank-excerpt'>{item.content}</p><small>{key==='before' ? 'RRF 分数' : '重排分数'} {item.score.toFixed(6)}</small>
              {key==='after' && <p><small>原排名 {item.fusion_rank} → 新排名 {item.rerank_rank}</small></p>}
            </button>)}
          </V2Panel>
        })}</div>
        {selected && <V2Panel><h2>来源定位</h2><p>{selected.document_name} · 片段 {selected.ordinal}</p><hr /><p className='v2-source-text'>{selected.content}</p>
          <V2Button kind='outline' onClick={()=>onAsk(result.question,'hybrid_rerank',metadataFilter)}>用此问题去问答</V2Button></V2Panel>}
      </>}
      {result.strategy==='hybrid' && <div className='v2-hybrid-grid'>
        {([['dense','向量召回','相似度'],['bm25','关键词召回','BM25 分数'],['fusion','RRF 融合','RRF 分数']] as const).map(([key,title,label])=>{
          const items=key==='fusion' ? result.items : result.branches?.[key] || []
          return <V2Panel key={key}><h2>{title}</h2><small>{items.length} 条 · 取各路前 {result.top_k} 条展示</small>
            {!items.length && <p>本路没有可用片段。</p>}
            {items.map(item=><button data-native-button type='button' key={item.chunk_id} className={`v2-evidence ${selected===item ? 'is-selected' : ''}`}
              onClick={()=>setSelected(item)} aria-pressed={selected===item}
            >
              <div className='v2-row'><span className='v2-rank'>{item.rank}</span><strong>{item.document_name}</strong></div>
              <p className='v2-hybrid-excerpt'>{item.content}</p><small>{label} {item.score.toFixed(key==='fusion' ? 6 : 3)}</small>
              {key==='fusion' && <p><small>向量排名 {item.dense_rank ?? '未召回'} · 关键词排名 {item.bm25_rank ?? '未召回'}</small></p>}
            </button>)}
          </V2Panel>
        })}
      </div>}
      {result.strategy==='hybrid' && selected && <V2Panel><h2>来源定位</h2><p>{selected.document_name} · 片段 {selected.ordinal}</p><hr />
        <p className='v2-source-text'>{selected.content}</p><V2Button kind='outline' onClick={()=>onAsk(result.question,'hybrid',metadataFilter)}>用此问题去问答</V2Button></V2Panel>}
      {result.strategy!=='hybrid' && result.strategy!=='hybrid_rerank' && <>
      {result.items.length === 0 ? <V2Panel className='v2-empty'><h2>{result.strategy === 'bm25' ? '没有匹配关键词的片段' : '没有找到可用资料'}</h2><p>可以换用资料中的关键词，或上传相关资料后重试。</p></V2Panel> :
        <div className='v2-two'><div>{result.items.map(item => <button data-native-button key={item.chunk_id} type='button' className={`v2-evidence ${selected?.chunk_id === item.chunk_id ? 'is-selected' : ''}`}
          onClick={() => setSelected(item)} aria-pressed={selected?.chunk_id === item.chunk_id}
        >
          <div className='v2-row'><span className='v2-rank'>{item.rank}</span><strong>{item.document_name}</strong></div>
          <p>{item.content}</p><small>{item.page_number ? `第 ${item.page_number} 页 · ` : ''}片段 {item.ordinal} · {result.strategy === 'bm25' ? 'BM25 分数' : '相似度'} {item.score.toFixed(3)}</small>
        </button>)}</div>
        {selected && <V2Panel><h2>片段 {selected.rank} · 来源定位</h2><p>{selected.document_name}</p>
          <small>{selected.page_number ? `第 ${selected.page_number} 页 · ` : ''}片段 {selected.ordinal}</small><hr /><p className='v2-source-text'>{selected.content}</p><hr />
          <V2Notice>{result.strategy === 'bm25' ? 'BM25分数仅用于相同问题与语料范围内排序，不能直接与余弦分数比较。' : '相似度是排序依据，不是回答正确概率。'}</V2Notice>
          <V2Button kind='outline' onClick={() => onAsk(result.question,result.strategy==='hybrid_rerank' ? 'hybrid_rerank' : strategy==='hybrid' ? 'hybrid' : 'dense',metadataFilter)}>用此问题去问答</V2Button>
        </V2Panel>}</div>}
      </>}
    </>}
  </div>
}
