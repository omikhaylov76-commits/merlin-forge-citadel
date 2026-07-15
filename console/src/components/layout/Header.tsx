import { useLocation } from 'react-router-dom'
import { NAV } from '@/lib/nav'
import { Button } from '@/components/ui/button'

function currentLabel(pathname: string): string {
  for (const g of NAV) for (const it of g.items) if (it.path === pathname) return it.label
  return 'Обзор'
}

// Хедер (h=60px по макету): хлебная крошка · поиск ⌘K · колокол · СТОП ФЛОТ (аварийный).
export function Header() {
  const { pathname } = useLocation()
  return (
    <header className="flex h-[60px] shrink-0 items-center gap-4 border-b border-line px-6">
      <div className="font-serif text-[17px] text-bone">{currentLabel(pathname)}</div>
      <div className="ml-2 hidden flex-1 items-center gap-2 rounded-pill border border-line bg-card px-4 py-2 text-[12px] text-ash md:flex">
        Поиск по флоту, клиентам, парам
        <kbd className="ml-auto rounded bg-floating px-1.5 py-0.5 text-[10px] text-fog">⌘K</kbd>
      </div>
      <button className="relative text-fog transition-colors hover:text-bone" aria-label="Уведомления">
        🔔
        <span className="absolute -right-1 -top-1 rounded-pill bg-danger px-1 text-[9px] font-semibold text-void">
          3
        </span>
      </button>
      <Button variant="danger" size="sm">
        СТОП ФЛОТ
      </Button>
    </header>
  )
}
