import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

/** Canonical V2 prototype controls. All workflow views share these owners. */
export function V2Heading({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className='v2-heading'><div><h1>{title}</h1><p>{description}</p></div><div className='v2-row'>{actions}</div></header>
}

export function V2Button({ children, onClick, kind = 'primary', disabled, type = 'button', icon, pressed }: {
  children: ReactNode; onClick?: () => void; kind?: 'primary' | 'outline' | 'ghost' | 'danger';
  disabled?: boolean; type?: 'button' | 'submit'; icon?: IconName; pressed?: boolean
}) {
  return <button data-native-button type={type} className={`v2-button v2-button-${kind}`} onClick={onClick} disabled={disabled} aria-pressed={pressed}>
    {icon && <Icon name={icon} />}{children}
  </button>
}

export function V2Notice({ children, danger = false }: { children: ReactNode; danger?: boolean }) {
  return <div className={`v2-notice ${danger ? 'v2-notice-danger' : ''}`} role={danger ? 'alert' : 'status'}>{children}</div>
}

export function V2Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`v2-panel ${className}`}>{children}</section>
}

export const percent = (value: number | null | undefined) => value == null ? '未统计' : `${Math.round(value * 100)}%`
