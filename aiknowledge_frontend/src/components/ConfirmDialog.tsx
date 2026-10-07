import { useEffect, useId, useRef } from 'react'
import { V2Button } from './V2UI'

export function ConfirmDialog({ title, description, action, onConfirm, onCancel }: {
  title: string; description: string; action: string; onConfirm: () => void; onCancel: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const id = useId()
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current
    element?.showModal()
    cancel.current?.focus()
    return () => { element?.close(); previous?.focus() }
  }, [])
  return <dialog ref={dialog} className='v2-dialog' aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}
    onCancel={event => { event.preventDefault(); onCancel() }}
  >
    <h2 id={`${id}-title`}>{title}</h2><p id={`${id}-description`}>{description}</p>
    <div className='v2-row'><button data-native-button ref={cancel} type='button' className='v2-button v2-button-outline' onClick={onCancel}>取消</button>
      <V2Button kind='danger' onClick={onConfirm}>{action}</V2Button></div>
  </dialog>
}
