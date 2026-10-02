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

const paths: Record<IconName, string> = {
  home: 'M3 7l9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10',
  chat: 'M4 4h16v12H9l-5 4z M8 8h8 M8 12h5',
  file: 'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6',
  feedback: 'M4 5h16v11H9l-5 4z M8 9h8 M8 12h5',
  eval: 'M5 4h14v17H5z M9 3h6v3H9z M8 10l2 2 5-4 M8 16h7',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
  bell: 'M6 8a6 6 0 0 1 12 0v7l2 3H4l2-3z M10 21h4',
  plus: 'M12 4v16 M4 12h16',
  arrow: 'M4 12h16 M14 6l6 6-6 6',
  upload: 'M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6',
  folder: 'M3 7l9-4 9 4v10l-9 4-9-4z M3 7l9 4 9-4 M12 11v10',
  book: 'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6',
  team: 'M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M4 21v-3a8 8 0 0 1 16 0v3',
  lock: 'M6 10h12v11H6z M8 10V6a4 4 0 0 1 8 0v4',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M3 12h18 M12 3c5 5 5 13 0 18 M12 3c-5 5-5 13 0 18',
  check: 'M5 12l4 4L19 6',
  warning: 'M12 3l10 18H2z M12 9v5 M12 17v1',
  close: 'M6 6l12 12 M18 6L6 18',
  send: 'M3 3l18 9-18 9 4-9z M7 12h14',
  link: 'M10 14l4-4 M9 16l-2 2a4 4 0 0 1-5-5l4-4 M15 8l2-2a4 4 0 0 1 5 5l-4 4',
  thumbUp: 'M8 10l4-7 3 1-1 6h7l-2 11H8z M3 10h5v11H3z',
  thumbDown: 'M8 14l4 7 3-1-1-6h7L19 3H8z M3 3h5v11H3z',
  copy: 'M9 9h12v12H9z M3 15V3h12',
  retry: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l4 2',
  trash: 'M4 7h16 M9 7V3h6v4 M6 7l1 14h10l1-14 M10 11v6 M14 11v6',
  menu: 'M3 6h18 M3 12h18 M3 18h18',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7v1'
}

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg aria-hidden='true' className={`glyph glyph-${name} ${className}`.trim()} viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth={1.7} strokeLinecap='round' strokeLinejoin='round'><path d={paths[name]} /></svg>
}
