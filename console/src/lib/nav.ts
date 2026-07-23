// Карта навигации консоли (по макету slash-console). group — подпись секции сайдбара.
export type NavItem = { path: string; label: string; icon: string; badge?: number; hot?: boolean }
export type NavGroup = { title?: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  { items: [{ path: '/', label: 'Обзор', icon: '◧' }] },
  {
    title: 'Флот',
    items: [
      { path: '/fleet', label: 'Флот', icon: '❈', badge: 19 },
      { path: '/deals', label: 'Сделки', icon: '⇄' },
    ],
  },
  { title: 'Клиенты', items: [{ path: '/clients', label: 'Клиенты', icon: '◑', badge: 12 }] },
  {
    // Конструктор ПЕРВЫМ (дизайн единой Разведки, подпись Куратора): «сначала конструирую бота →
    // потом смотрю его глазами» (Разведка рядом). Пересмотр — когда флот встанет (3-5 ботов).
    title: 'Кузница',
    items: [
      { path: '/constructor', label: 'Конструктор', icon: '✦' },
      { path: '/scout', label: 'Разведка', icon: '◎' },
      { path: '/screener', label: 'Скринер', icon: '⌕' },
      { path: '/basket', label: 'Набор', icon: '★' },
      { path: '/profiles', label: 'Профили', icon: '▤' },
    ],
  },
  {
    title: 'Журналы',
    items: [
      { path: '/signals', label: 'Сигналы', icon: '⟐' },
      { path: '/reports', label: 'Отчёты', icon: '▦' },
      { path: '/alerts', label: 'Тревоги', icon: '◈', badge: 3, hot: true },
    ],
  },
  {
    title: 'Система',
    items: [
      { path: '/settings', label: 'Настройки', icon: '⚙' },
      { path: '/portal', label: 'Портал клиента', icon: '◐' },
    ],
  },
]
