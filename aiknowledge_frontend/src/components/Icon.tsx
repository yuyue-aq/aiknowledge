import { Text } from '@tarojs/components'

export type IconName =
  | 'home'
  | 'chat'
  | 'file'
  | 'feedback'
  | 'eval'
  | 'settings'
  | 'search'
  | 'bell'
  | 'plus'
  | 'arrow'
  | 'upload'
  | 'folder'
  | 'book'
  | 'team'
  | 'lock'
  | 'globe'
  | 'check'
  | 'warning'
  | 'close'
  | 'send'
  | 'link'
  | 'thumbUp'
  | 'thumbDown'
  | 'copy'
  | 'retry'
  | 'trash'
  | 'menu'
  | 'info'

const symbols: Record<IconName, string> = {
  home: '⌂',
  chat: '▱',
  file: '▤',
  feedback: '◌',
  eval: '◈',
  settings: '⚙',
  search: '⌕',
  bell: '♧',
  plus: '+',
  arrow: '›',
  upload: '⇧',
  folder: '▰',
  book: '▥',
  team: '♧',
  lock: '▣',
  globe: '◎',
  check: '✓',
  warning: '!',
  close: '×',
  send: '➤',
  link: '↗',
  thumbUp: '♧',
  thumbDown: '♧',
  copy: '▣',
  retry: '↻',
  trash: '♲',
  menu: '☰',
  info: 'i'
}

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <Text aria-hidden='true' className={`glyph glyph-${name} ${className}`.trim()}>{symbols[name]}</Text>
}
