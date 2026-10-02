import type { ButtonHTMLAttributes } from 'react'

/** Shared H5 control: native keyboard, focus and disabled semantics. */
export function Button({ size: _size, onClick, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { size?: 'mini' | 'default' }) {
  return <button type='button' data-native-button onClick={onClick} {...props} />
}
