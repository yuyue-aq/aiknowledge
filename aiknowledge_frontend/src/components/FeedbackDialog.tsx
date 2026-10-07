import { useEffect, useId, useRef, useState } from 'react'
import type { FeedbackReason } from '../api/client'
import { V2Button, V2Notice } from './V2UI'

const reasons: Array<[FeedbackReason, string]> = [['OFF_TOPIC', '答非所问'], ['SOURCE_MISMATCH', '来源不匹配'], ['OUTDATED', '资料过时'], ['INCOMPLETE', '回答不完整'], ['MISSING_MATERIAL', '缺少资料']]

export function FeedbackDialog({ onCancel, onSubmit }: {
  onCancel: () => void; onSubmit: (reason: FeedbackReason, comment: string) => Promise<void>
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const first = useRef<HTMLInputElement>(null)
  const id = useId()
  const [reason, setReason] = useState<FeedbackReason | null>(null)
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current; element?.showModal(); first.current?.focus()
    return () => { element?.close(); previous?.focus() }
  }, [])
  return <dialog ref={dialog} className='v2-dialog v2-page' aria-labelledby={id + '-title'} onCancel={event => { event.preventDefault(); if (!submitting.current) onCancel() }}>
    <h2 id={id + '-title'}>提交反馈</h2><p>指出问题，帮助完善资料与回答。</p>
    <form noValidate onSubmit={event => {
      event.preventDefault()
      if (submitting.current) return
      if (!reason) { setError('请选择一个反馈原因。'); first.current?.focus(); return }
      submitting.current = true; setBusy(true); setError('')
      void onSubmit(reason, comment.trim()).catch(failure => setError(failure instanceof Error ? failure.message : '反馈保存失败，请重试。'))
        .finally(() => { submitting.current = false; setBusy(false) })
    }}
    >
      <fieldset><legend>反馈原因</legend>{reasons.map(([value, label], index) => <label key={value} className='v2-row'>
        <input data-v2-control ref={index === 0 ? first : undefined} type='radio' name='feedback-reason' checked={reason === value} onChange={() => setReason(value)} />{label}
      </label>)}</fieldset>
      <label htmlFor={id + '-comment'}>补充说明（可选）</label><textarea data-v2-control className='resize-none' id={id + '-comment'} value={comment} maxLength={1000} onChange={event => setComment(event.target.value)} placeholder='期望的答案、缺失内容或需要更新的资料' />
      {error && <V2Notice danger>{error}</V2Notice>}
      <div className='v2-row'><V2Button type='submit' disabled={busy}>{busy ? '正在提交…' : '提交反馈'}</V2Button><V2Button kind='outline' disabled={busy} onClick={onCancel}>取消</V2Button></div>
    </form>
  </dialog>
}
