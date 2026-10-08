import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiRequestError, getAuthUserId, getEvalEvidence, type EvalEvidence, listEvalCases, listEvalRuns, listEvalVersions, createEvalCase, updateEvalCase, deleteEvalCase,
  createEvalVersion, enqueueEvaluation, enqueueEvalVersion, getEvalRun, retryEvalRun, reviewEvalResult,
  compareEvalRuns, searchKnowledge, listDocuments, getOwnerDocumentDetail, type KnowledgeDocument, type Category, type EvalCase, type EvalDetail, type EvalRun,
  type EvalRunComparison, type EvalSetVersion, type EvidenceRef, type RetrievalItem,
} from '../api/client'
import { V2Button, V2Heading, V2Notice, V2Panel, percent } from './V2UI'
import { ConfirmDialog } from './ConfirmDialog'
import './v2.scss'

type Page = 'cases' | 'edit' | 'select' | 'run' | 'grade' | 'compare'
type Draft = {
  id?: string; question: string; expected_answer: string; scope: EvalCase['scope']; category_ids: string[];
  answerable: boolean; expected_behavior: string; expected_document_ids: string[]; evidence_refs: EvidenceRef[]
}
const newDraft = (): Draft => ({ question: '', expected_answer: '', scope: 'OWNER', category_ids: [], answerable: true,
  expected_behavior: 'ANSWERED', expected_document_ids: [], evidence_refs: [] })
const failureText = (failure: unknown) => failure instanceof ApiRequestError ? failure.message : '操作暂时无法完成，请稍后重试。'
const answerLabel: Record<string, string> = { ANSWERED: '已回答', INSUFFICIENT_EVIDENCE: '资料不足', OUT_OF_SCOPE: '范围外问题', CONFLICT: '资料冲突', FAILED: '调用失败' }

const draftKey = (spaceId: string) => 'zhisu.eval-draft.' + (getAuthUserId() || 'anonymous') + '.' + spaceId
function restoredDraft(spaceId: string): Draft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(draftKey(spaceId)) || 'null')
    return value && typeof value.question === 'string' && typeof value.expected_answer === 'string' &&
      Array.isArray(value.evidence_refs) && Array.isArray(value.category_ids) && Array.isArray(value.expected_document_ids) ? value : null
  } catch { return null }
}

export function EvaluationView({ spaceId, categories, notify, initialQuestion = '', initialAnswer = '', onSeedConsumed }: {
  spaceId: string; categories: Category[]; notify: (message: string) => void; initialQuestion?: string; initialAnswer?: string; onSeedConsumed?: () => void
}) {
  const [page, setPage] = useState<Page>(initialQuestion || restoredDraft(spaceId) ? 'edit' : 'cases')
  const seedConsumed = useRef(false)
  useEffect(() => {
    if (initialQuestion && !seedConsumed.current) {
      seedConsumed.current = true
      onSeedConsumed?.()
    }
  }, [initialQuestion, onSeedConsumed])
  const [cases, setCases] = useState<EvalCase[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [versions, setVersions] = useState<EvalSetVersion[]>([])
  const [versionId, setVersionId] = useState('')
  const [strategy,setStrategy]=useState<'dense' | 'hybrid' | 'hybrid_rerank'>('dense')
  const [versionLabel, setVersionLabel] = useState('')
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState<Draft>(() => initialQuestion ? { ...newDraft(), question: initialQuestion, expected_answer: initialAnswer } : restoredDraft(spaceId) || newDraft())
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<EvalDetail | null>(null)
  const [activeRun, setActiveRun] = useState<EvalRun | null>(null)
  const [gradingId, setGradingId] = useState('')
  const [gradeEvidence, setGradeEvidence] = useState<EvalEvidence | null>(null)
  const [evidenceError, setEvidenceError] = useState('')
  const [score, setScore] = useState<0 | .5 | 1 | null>(null)
  const [reviewNote, setReviewNote] = useState('')
  const [baselineId, setBaselineId] = useState('')
  const [candidateId, setCandidateId] = useState('')
  const [comparison, setComparison] = useState<EvalRunComparison | null>(null)
  const [evidence, setEvidence] = useState<RetrievalItem[]>([])
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [evidenceDocumentId, setEvidenceDocumentId] = useState('')
  const [deleting, setDeleting] = useState<EvalCase | null>(null)
  const [leavingDraft, setLeavingDraft] = useState(false)
  const initialDraft = useRef(JSON.stringify({ ...newDraft(), question: initialQuestion, expected_answer: initialAnswer }))
  const alive = useRef(true)
  const request = useRef<AbortController | null>(null)
  const mutating = useRef(false)
  useEffect(() => {
    try {
      if (page === 'edit' || page === 'select') sessionStorage.setItem(draftKey(spaceId), JSON.stringify(draft))
      else sessionStorage.removeItem(draftKey(spaceId))
    } catch { /* The editor continues when browser storage is unavailable. */ }
  }, [draft, page, spaceId])

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [nextCases, nextRuns, nextVersions, nextDocuments] = await Promise.all([listEvalCases(spaceId), listEvalRuns(spaceId), listEvalVersions(spaceId), listDocuments(spaceId)])
      if (!alive.current) return
      setCases(nextCases); setRuns(nextRuns); setVersions(nextVersions)
      setDocuments(nextDocuments)
    } catch (failure) { if (alive.current) setError(failureText(failure)) }
    finally { if (alive.current) setLoading(false) }
  }, [spaceId])
  useEffect(() => { alive.current = true; void load(); return () => { alive.current = false; request.current?.abort() } }, [load])

  // One sequential poll, cancelled on route unmount and hidden browser tab.
  const runId = activeRun?.id
  const runStatus = activeRun?.status
  useEffect(() => {
    if (!runId || !runStatus || !['PENDING', 'RUNNING'].includes(runStatus)) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    let inFlight = false
    const controller = new AbortController()
    request.current = controller
    const poll = async () => {
      if (stopped || document.hidden || inFlight) return
      inFlight = true
      try {
        const next = await getEvalRun(runId, controller.signal)
        if (stopped) return
        failures = 0; setError(''); setDetail(next); setActiveRun(next.run)
        setRuns(items => [next.run, ...items.filter(item => item.id !== next.run.id)])
        if (['PENDING', 'RUNNING'].includes(next.run.status)) timer = setTimeout(() => void poll(), 2000)
      } catch (failure) {
        if (stopped || controller.signal.aborted) return
        failures++
        setError(failureText(failure))
        if (failures < 3) timer = setTimeout(() => void poll(), 2000)
      } finally { inFlight = false }
    }
    const visibility = () => { if (document.hidden) clearTimeout(timer); else void poll() }
    document.addEventListener('visibilitychange', visibility)
    void poll()
    return () => { stopped = true; controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', visibility) }
  }, [runId, runStatus])

  const perform = async (action: () => Promise<void>) => {
    if (mutating.current) return
    mutating.current = true
    setBusy(true); setError('')
    try { await action() } catch (failure) { if (alive.current) setError(failureText(failure)) }
    finally { mutating.current = false; if (alive.current) setBusy(false) }
  }
  const edit = (item?: EvalCase) => {
    setError('')
    const nextDraft = item ? { id: item.id, question: item.question, expected_answer: item.expected_answer || '', scope: item.scope,
      category_ids: item.category_ids, answerable: item.answerable !== false, expected_behavior: item.expected_behavior || 'ANSWERED',
      expected_document_ids: item.expected_document_ids, evidence_refs: item.evidence_refs || [] } : newDraft()
    initialDraft.current = JSON.stringify(nextDraft)
    setDraft(nextDraft)
    setPage('edit')
  }
  const leaveEditor = () => {
    if (JSON.stringify(draft) !== initialDraft.current) setLeavingDraft(true)
    else setPage('cases')
  }
  const save = async () => {
    if (!draft.question.trim()) { setError('请输入测试问题。'); document.getElementById('case-question')?.focus(); return }
    if (draft.scope !== 'OWNER' && !draft.category_ids.length) { setError('请选择测试的公开分类。'); return }
    await perform(async () => {
      const input = { ...draft, question: draft.question.trim(), expected_answer: draft.expected_answer.trim() || null }
      const saved = draft.id ? await updateEvalCase(draft.id, input) : await createEvalCase(spaceId, input)
      if (!alive.current) return
      setCases(items => [saved, ...items.filter(item => item.id !== saved.id)])
      setPage('cases'); notify('测试题已保存。')
    })
  }
  const selectEvidence = async () => {
    if (!draft.question.trim()) { setError('请先填写问题，再选择相关证据。'); return }
    setPage('select')
    setEvidence([]); setEvidenceDocumentId('')
    await perform(async () => {
      const found = await searchKnowledge(spaceId, draft.question.trim(), 10)
      if (alive.current) setEvidence(found.items)
    })
  }
  const start = () => perform(async () => {
    const run = versionId ? await enqueueEvalVersion(versionId,strategy) : await enqueueEvaluation(spaceId,strategy)
    if (!alive.current) return
    setActiveRun(run); setDetail(null); setRuns(items => [run, ...items.filter(item => item.id !== run.id)]); setPage('run')
  })
  const openRun = (selectedRunId: string, destination: Page = 'grade') => perform(async () => {
    const next = await getEvalRun(selectedRunId)
    if (!alive.current) return
    setDetail(next); setActiveRun(next.run); setPage(destination); setGradingId(next.results[0]?.id || '')
    setScore(next.results[0]?.reviewer_score as 0 | .5 | 1 | null); setReviewNote(next.results[0]?.reviewer_note || '')
  })
  const frozenCases = (detail?.run.retrieval_config_snapshot.eval_cases || []) as EvalCase[]
  const selectedResult = detail?.results.find(item => item.id === gradingId) || detail?.results[0]
  const selectedCase = frozenCases.find(item => item.id === selectedResult?.eval_case_id)
  const selectedResultId = selectedResult?.id
  const gradingRunId = detail?.run.id
  useEffect(() => {
    setGradeEvidence(null); setEvidenceError('')
    if (page !== 'grade' || !selectedResultId || !gradingRunId) return
    const controller = new AbortController()
    void getEvalEvidence(gradingRunId, selectedResultId, controller.signal).then(next => {
      if (!controller.signal.aborted) setGradeEvidence(next)
    }).catch(failure => { if (!controller.signal.aborted) setEvidenceError(failureText(failure)) })
    return () => controller.abort()
  }, [page, selectedResultId, gradingRunId])
  const total = activeRun?.progress_total || frozenCases.length
  const completed = activeRun?.progress_completed ?? detail?.results.length ?? 0

  const toggleEvidence = (item: RetrievalItem, selected: boolean) => {
    if (!item.document_version_id || item.source_block_id == null || item.char_start == null || item.char_end == null || !item.content_hash) return
    const ref: EvidenceRef = { document_id: item.document_id, document_version_id: item.document_version_id,
      source_block_id: item.source_block_id, char_start: item.char_start, char_end: item.char_end, text_hash: item.content_hash, required: true }
    setDraft(current => {
      const refs = current.evidence_refs.filter(value => !(value.document_version_id === ref.document_version_id && value.source_block_id === ref.source_block_id && value.char_start === ref.char_start))
      if (selected) refs.push(ref)
      return { ...current, evidence_refs: refs, expected_document_ids: [...new Set(refs.map(value => value.document_id))] }
    })
  }

  return <div className='v2-page'>
    {page === 'cases' && <>
      <V2Heading title='质量自测' description='用固定问题验证资料与回答效果。' actions={<V2Button icon='plus' onClick={() => edit()}>添加测试题</V2Button>} />
      <div className='v2-row'><select data-v2-control aria-label='运行题集版本' value={versionId} onChange={event => setVersionId(event.target.value)} className='v2-compact-select'>
        <option value=''>当前题集 · {cases.length} 题</option>{versions.map(version => <option key={version.id} value={version.id}>v{version.version_number} · {version.label}</option>)}</select>
        <select data-v2-control aria-label='评测检索方式' disabled={busy} className='v2-compact-select' value={strategy} onChange={event=>setStrategy(event.target.value as 'dense' | 'hybrid' | 'hybrid_rerank')}><option value='dense'>向量检索基线</option><option value='hybrid'>混合检索 · RRF</option><option value='hybrid_rerank'>混合检索 + 模型重排</option></select>
        <V2Button kind='outline' disabled={busy || !(versionId ? versions.find(version => version.id === versionId)?.cases.length : cases.length)} onClick={() => void start()}>运行题集</V2Button>
        <V2Button kind='ghost' disabled={runs.length < 2} onClick={() => setPage('compare')}>基线与复测对比</V2Button></div>
      <div className='v2-row v2-between'><input data-v2-control aria-label='搜索测试问题' placeholder='搜索测试问题…' value={query} onChange={event => setQuery(event.target.value)} className='v2-search-input' />
        <form noValidate className='v2-row' onSubmit={event => { event.preventDefault(); if (versionLabel.trim()) void perform(async () => {
          const version = await createEvalVersion(spaceId, versionLabel.trim()); if (!alive.current) return
          setVersions(items => [version, ...items]); setVersionId(version.id); setVersionLabel(''); notify('题集版本已保存。')
        }) }}
        ><input data-v2-control aria-label='题集版本名称' placeholder='版本名称' value={versionLabel} onChange={event => setVersionLabel(event.target.value)} className='v2-version-input' />
          <V2Button type='submit' kind='outline' disabled={busy || !versionLabel.trim() || !cases.length}>保存题集版本</V2Button></form></div>
      <V2Panel>{loading ? <p role='status'>正在加载题集…</p> : cases.length === 0 ? <div className='v2-empty'><h2>还没有测试题</h2><p>添加一个真实问题、标准答案和证据，开始检查资料质量。</p></div> :
        <div className='v2-table-wrap'><table className='v2-table'><thead><tr><th>问题</th><th>范围</th><th>预期行为</th><th>操作</th></tr></thead><tbody>
          {cases.filter(item => item.question.includes(query)).map(item => <tr key={item.id}><td>{item.question}</td><td>{item.scope === 'OWNER' ? '拥有者' : '公开分类'}</td>
            <td>{item.answerable == null ? '待标注' : item.answerable ? '应回答' : '应拒答'}</td><td><div className='v2-row'><V2Button kind='ghost' onClick={() => edit(item)}>编辑</V2Button>
              <V2Button kind='ghost' onClick={() => setDeleting(item)}>删除</V2Button></div></td></tr>)}</tbody></table></div>}</V2Panel>
      {runs.length > 0 && <V2Panel><h2>最近运行</h2>{runs.map(run => <div key={run.id} className='v2-row v2-between'><span>{new Date(run.created_at).toLocaleString('zh-CN')} · {run.status === 'COMPLETED' ? '已完成' : run.status === 'FAILED' ? '失败' : '处理中'}</span>
        <V2Button kind='ghost' onClick={() => void openRun(run.id, ['PENDING', 'RUNNING'].includes(run.status) ? 'run' : 'grade')}>打开运行</V2Button></div>)}</V2Panel>}
    </>}

    {page === 'edit' && <>
      <V2Heading title={draft.id ? '编辑测试题' : '添加测试题'} description='完善问题、标准答案与访问范围。' actions={<V2Button kind='outline' onClick={leaveEditor}>返回题集</V2Button>} />
      <V2Panel><form noValidate onSubmit={event => { event.preventDefault(); void save() }}>
        <label htmlFor='case-question'>问题</label><textarea data-v2-control className='resize-none' id='case-question' maxLength={2000} value={draft.question} onChange={event => setDraft({ ...draft, question: event.target.value })} />
        <div className='v2-two'><div><label htmlFor='case-scope'>测试范围</label><select data-v2-control id='case-scope' value={draft.scope} onChange={event => {
          const scope = event.target.value as EvalCase['scope']; setDraft({ ...draft, scope, category_ids: scope === 'OWNER' ? [] : categories.filter(item => item.is_open).slice(0, 1).map(item => item.id) })
        }}
        ><option value='OWNER'>拥有者</option><option value='PUBLIC'>公开分类</option><option value='OUT_OF_SCOPE'>公开分类 · 范围外问题</option></select></div>
          <div><label htmlFor='case-behavior'>预期行为</label><select data-v2-control id='case-behavior' value={draft.expected_behavior} onChange={event => setDraft({ ...draft, expected_behavior: event.target.value, answerable: event.target.value === 'ANSWERED' })}>
            <option value='ANSWERED'>应回答</option><option value='INSUFFICIENT_EVIDENCE'>资料不足，应拒答</option><option value='OUT_OF_SCOPE'>范围外，应拒答</option><option value='CONFLICT'>指出资料冲突</option></select></div></div>
        {draft.scope !== 'OWNER' && <><label htmlFor='case-category'>公开分类</label><select data-v2-control id='case-category' value={draft.category_ids[0] || ''} onChange={event => setDraft({ ...draft, category_ids: event.target.value ? [event.target.value] : [] })}>
          <option value=''>请选择分类</option>{categories.map(category => <option key={category.id} value={category.id}>{category.name}{category.is_open ? '' : ' · 未开放'}</option>)}</select></>}
        <label htmlFor='case-answer'>标准答案与评分要点</label><textarea data-v2-control className='resize-none' id='case-answer' maxLength={5000} value={draft.expected_answer} onChange={event => setDraft({ ...draft, expected_answer: event.target.value })} />
        <div className='v2-row v2-between'><strong>相关证据 · {draft.evidence_refs.length} 条</strong><V2Button kind='outline' disabled={busy} onClick={() => void selectEvidence()}>选择证据</V2Button></div>
        {draft.evidence_refs.map(ref => <p key={`${ref.document_version_id}-${ref.source_block_id}-${ref.char_start}`}><small>{ref.source_block_id} · 区间 {ref.char_start}—{ref.char_end}</small></p>)}
        <hr /><div className='v2-row'><V2Button type='submit' disabled={busy}>{busy ? '正在保存…' : '保存测试题'}</V2Button><V2Button kind='outline' onClick={leaveEditor}>取消</V2Button></div>
      </form></V2Panel>
    </>}

    {page === 'select' && <>
      <V2Heading title='选择相关证据' description='标记哪些资料支持标准答案。' actions={<V2Button kind='outline' onClick={() => setPage('edit')}>返回编辑</V2Button>} />
      <V2Panel><form noValidate className='v2-row' onSubmit={event => { event.preventDefault(); if (evidenceDocumentId) void perform(async () => {
        setEvidence([])
        const next = await getOwnerDocumentDetail(spaceId, evidenceDocumentId)
        if (alive.current) setEvidence(next.chunks)
      }) }}
      ><label htmlFor='evidence-document'>按文档浏览证据</label><select data-v2-control id='evidence-document' className='v2-compact-select' value={evidenceDocumentId} onChange={event => setEvidenceDocumentId(event.target.value)}>
        <option value=''>选择文档</option>{documents.map(item => <option key={item.id} value={item.id}>{item.original_filename}</option>)}</select><V2Button type='submit' kind='outline' disabled={busy || !evidenceDocumentId}>浏览片段</V2Button></form>
        <small>检索结果只是参考。可直接浏览资料标注标准证据，检索未命中不改变标准答案。</small></V2Panel>
      <div className='v2-two'><V2Panel><h2>当前问题</h2><p>{draft.question}</p><hr /><strong>标准答案所需证据</strong><p>{draft.expected_answer || '请结合标准答案选择支持它的资料片段。'}</p>
        <V2Button onClick={() => setPage('edit')}>保存选择</V2Button></V2Panel><div>{busy && <p role='status'>正在查找证据…</p>}
        {evidence.map(item => {
          const supported = item.document_version_id && item.source_block_id != null && item.char_start != null && item.char_end != null && item.content_hash
          const selected = draft.evidence_refs.some(ref => ref.document_version_id === item.document_version_id && ref.source_block_id === item.source_block_id && ref.char_start === item.char_start)
          return <V2Panel key={item.chunk_id}><label className='v2-row'><input data-v2-control type='checkbox' checked={selected} disabled={!supported} onChange={event => toggleEvidence(item, event.target.checked)} />使用此证据</label>
            <strong>{item.document_name}</strong><p className='v2-source-text'>{item.content}</p><small>{item.page_number ? `第 ${item.page_number} 页 · ` : ''}片段 {item.ordinal}</small>
            {!supported && <V2Notice>此旧片段缺少原文定位，请更新资料后再标注证据。</V2Notice>}</V2Panel>
        })}{!busy && !evidence.length && <V2Notice>没有找到可标注的证据，可以补充资料或修改问题后重试。</V2Notice>}</div></div>
    </>}

    {page === 'run' && <>
      <V2Heading title='运行质量自测' description={activeRun ? `运行 ${new Date(activeRun.created_at).toLocaleString('zh-CN')}` : '题集与资料已冻结'} actions={<V2Button kind='outline' disabled={!detail?.results.length} onClick={() => setPage('grade')}>查看评分</V2Button>} />
      <V2Panel><div className='v2-row v2-between'><h2>{activeRun?.status === 'COMPLETED' ? '运行完成' : activeRun?.status === 'FAILED' ? '运行未完成' : '正在检查题目'}</h2><small>保留已完成结果 · {activeRun?.retrieval_config_snapshot?.retrieval_strategy==='hybrid_rerank' ? '模型重排' : activeRun?.retrieval_config_snapshot?.retrieval_strategy==='hybrid' ? '混合检索' : '向量检索'}</small></div>
        <strong>已完成 {completed} / {total} 题</strong><div className='v2-progress' role='progressbar' aria-valuenow={completed} aria-valuemin={0} aria-valuemax={total || 1}><span style={{ width: `${total ? completed / total * 100 : 0}%` }} /></div>
        {activeRun?.failure_message && <V2Notice danger>{activeRun.failure_message}</V2Notice>}
        <div className='v2-row'><V2Button kind='outline' onClick={() => setPage('cases')}>返回题集</V2Button>
          {activeRun && (activeRun.status === 'FAILED' || activeRun.failure_code === 'QUEUE_UNAVAILABLE') && <V2Button disabled={busy} onClick={() => void perform(async () => {
            const next = await retryEvalRun(activeRun.id)
            if (alive.current) { setActiveRun(next); setPage('run'); setError('') }
          })}
          >恢复未完成任务</V2Button>}
          {error && activeRun && <V2Button kind='outline' onClick={() => void openRun(activeRun.id, 'run')}>重新读取进度</V2Button>}</div></V2Panel>
      <div className='v2-kpis'>{[['已完成', completed], ['调用失败', detail?.summary.failed || 0], ['待处理', Math.max(0, total - completed)], ['待人工评分', detail?.results.filter(item => item.reviewer_score == null).length || 0]].map(([label, value]) =>
        <div className='v2-kpi' key={label}><small>{label}</small><strong>{value}</strong></div>)}</div>
      <V2Notice>运行完成不等于回答全部正确，需逐题人工评分。</V2Notice>
      <V2Panel><h2>最近完成</h2>{detail?.results.slice(-5).map(item => <div className='v2-row v2-between' key={item.id}><span>{frozenCases.find(question => question.id === item.eval_case_id)?.question || '历史题目'}</span><small>{answerLabel[item.answer_status] || item.answer_status}</small></div>)}</V2Panel>
    </>}

    {page === 'grade' && <>
      <V2Heading title='人工评分' description='核对答案与证据，记录真实问题。' actions={<V2Button kind='outline' onClick={() => setPage('compare')}>运行对比</V2Button>} />
      <div className='v2-two v2-grade-layout'><aside className='v2-case-list'>{detail?.results.map((item, index) => <button data-native-button key={item.id} type='button' aria-pressed={selectedResult?.id === item.id}
        onClick={() => { setGradingId(item.id); setScore(item.reviewer_score as 0 | .5 | 1 | null); setReviewNote(item.reviewer_note || '') }}
      >
        {String(index + 1).padStart(2, '0')} · {frozenCases.find(question => question.id === item.eval_case_id)?.question || '历史题目'}<p><small>{item.reviewer_score == null ? '待评分' : item.reviewer_score === 1 ? '正确' : item.reviewer_score === .5 ? '部分正确' : '错误'}</small></p></button>)}</aside>
        {selectedResult ? <V2Panel><h2>{selectedCase?.question || '历史题目'}</h2><small>{selectedCase?.scope === 'OWNER' ? '拥有者' : '公开分类'} · {answerLabel[selectedResult.answer_status]}</small>
          <hr /><strong>标准答案</strong><p>{selectedCase?.expected_answer || '未标注标准答案'}</p><hr /><strong>实际回答</strong><p className='v2-source-text'>{selectedResult.answer}</p>
          <V2Notice>文档 Recall@K：{percent(selectedResult.retrieval_metrics?.document_recall_at_k as number | null)} · 证据完整覆盖：{percent(selectedResult.retrieval_metrics?.evidence_recall_at_k as number | null)}</V2Notice>
          <h2>当次检索依据</h2>{evidenceError && <V2Notice danger>{evidenceError}</V2Notice>}
          {!gradeEvidence && !evidenceError && <p role='status'>正在读取当次依据…</p>}
          {gradeEvidence && !gradeEvidence.snapshot_available && <V2Notice>这次历史运行未记录候选快照，无法核对检索依据。</V2Notice>}
          {gradeEvidence?.unavailable_chunk_ids.length ? <V2Notice>部分当次依据已失效或版本已更新，当前不能查看其原文。</V2Notice> : null}
          {gradeEvidence?.items.map(item => <details key={item.chunk_id}><summary>#{item.rank} · {item.document_name} · {item.score.toFixed(3)}</summary><p className='v2-source-text'>{item.content}</p></details>)}
          <div className='v2-row'>{([1, .5, 0] as const).map(value => <V2Button key={value} kind='outline' pressed={score === value} onClick={() => setScore(value)}>{value === 1 ? '正确' : value === .5 ? '部分正确' : '错误'}</V2Button>)}</div>
          <label htmlFor='review-note'>评分说明</label><textarea data-v2-control className='resize-none' id='review-note' maxLength={1000} value={reviewNote} onChange={event => setReviewNote(event.target.value)} placeholder='记录遗漏、来源不匹配或资料缺失' />
          <V2Button disabled={busy || score == null} onClick={() => void perform(async () => {
            if (score == null) return
            await reviewEvalResult(selectedResult.id, { reviewer_score: score, reviewer_note: reviewNote.trim() || null })
            const next = await getEvalRun(detail!.run.id); if (alive.current) { setDetail(next); notify('人工评分已保存。') }
          })}
          >保存评分</V2Button></V2Panel> : <V2Panel><p>还没有完成的题目可供评分。</p><V2Button kind='outline' onClick={() => setPage('cases')}>返回题集</V2Button></V2Panel>}</div>
    </>}

    {page === 'compare' && <>
      <V2Heading title='基线与复测对比' description='选择同一题集的两次运行，比较实际结果。' actions={<V2Button kind='outline' onClick={() => setPage('cases')}>返回题集</V2Button>} />
      <V2Panel><form noValidate className='v2-query' onSubmit={event => { event.preventDefault(); void perform(async () => {
        if (!baselineId || !candidateId || baselineId === candidateId) { setError('请选择两次不同的运行。'); return }
        const next = await compareEvalRuns(spaceId, baselineId, candidateId); if (alive.current) setComparison(next)
      }) }}
      ><div><label htmlFor='baseline'>基线</label><select data-v2-control id='baseline' value={baselineId} onChange={event => setBaselineId(event.target.value)}><option value=''>选择基线</option>{runs.map(run => <option key={run.id} value={run.id}>{new Date(run.created_at).toLocaleString('zh-CN')}</option>)}</select></div>
        <div><label htmlFor='candidate'>复测</label><select data-v2-control id='candidate' value={candidateId} onChange={event => setCandidateId(event.target.value)}><option value=''>选择复测</option>{runs.map(run => <option key={run.id} value={run.id}>{new Date(run.created_at).toLocaleString('zh-CN')}</option>)}</select></div>
        <V2Button type='submit' disabled={busy}>生成对比</V2Button></form></V2Panel>
      {comparison && <>
        {!comparison.same_test_set && <V2Notice danger>题集、标准答案或标注发生变化，以下结果用于核对，不能作为同题集质量提升结论。</V2Notice>}
        <V2Notice>{JSON.stringify(comparison.baseline.retrieval_config_snapshot.knowledge_manifest) === JSON.stringify(comparison.candidate.retrieval_config_snapshot.knowledge_manifest)
          ? '资料清单一致，请结合题集与配置判断变化。' : '此次资料或访问范围发生变化，变化不能全部归因于检索算法。'}</V2Notice>
        <div className='v2-two'>{([['基线', comparison.baseline, comparison.baseline_summary], ['复测', comparison.candidate, comparison.candidate_summary]] as const).map(([label, run, summary]) =>
          <V2Panel key={label}><h2>{label}</h2><small>{new Date(run.created_at).toLocaleString('zh-CN')}</small><div className='v2-kpi'><small>回答完全正确 · 已评分</small><strong>{percent(summary.answer_accuracy)}</strong><small>评分覆盖 {percent(summary.reviewed_coverage)}</small></div>
            <p>文档 Recall@K · {percent(summary.document_recall_at_k)}</p><p>文档 Hit@K · {percent(summary.document_hit_at_k)}</p><p>证据完整覆盖 · {percent(summary.evidence_recall_at_k)}</p><p>调用失败 · {summary.failed}</p></V2Panel>)}</div>
        <V2Panel><h2>逐题变化</h2><div className='v2-table-wrap'><table className='v2-table'><thead><tr><th>问题</th><th>基线</th><th>复测</th><th>人工评分</th></tr></thead><tbody>
          {comparison.question_changes.map(item => <tr key={item.eval_case_id}><td>{item.candidate_question || item.baseline_question}{!item.comparable && <p><small>题目或标注变化</small></p>}</td>
            <td>{item.baseline_status ? answerLabel[item.baseline_status] : '未完成'}</td><td>{item.candidate_status ? answerLabel[item.candidate_status] : '未完成'}</td><td>{item.baseline_score ?? '未评分'} → {item.candidate_score ?? '未评分'}</td></tr>)}
        </tbody></table></div></V2Panel>
      </>}
    </>}
    {error && <V2Notice danger>{error}{page === 'cases' && <V2Button kind='outline' onClick={() => void load()}>重新加载</V2Button>}</V2Notice>}
    {leavingDraft && <ConfirmDialog title='放弃未保存的修改' description='当前测试题尚未保存。离开后，这些修改不会写入题集。' action='放弃修改'
      onCancel={() => setLeavingDraft(false)} onConfirm={() => { setLeavingDraft(false); setPage('cases') }}
    />}
    {deleting && <ConfirmDialog title='删除测试题' description={`删除“${deleting.question}”？已有历史结果的题目会保留，并提示不能删除。`} action='删除测试题'
      onCancel={() => setDeleting(null)} onConfirm={() => { const target = deleting; setDeleting(null); void perform(async () => {
        await deleteEvalCase(target.id); if (alive.current) { setCases(items => items.filter(item => item.id !== target.id)); notify('测试题已删除。') }
      }) }}
    />}
  </div>
}
