import { type ReactNode } from 'react'
import { cn } from '@/lib/cn'

// Шапка экрана (по макету): eyebrow-раздел + серифный заголовок + описание + действие справа.
export function PageHead({
  eyebrow,
  title,
  desc,
  action,
}: {
  eyebrow: string
  title: string
  desc?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="text-[11px] uppercase tracking-widest text-ash">{eyebrow}</div>
        <div className="font-serif text-[28px] leading-tight text-bone">{title}</div>
        {desc && <div className="mt-0.5 text-[13px] text-fog">{desc}</div>}
      </div>
      {action}
    </div>
  )
}

export function Toolbar({ children }: { children: ReactNode }) {
  return <div className="mb-4 flex flex-wrap items-center gap-2">{children}</div>
}

// Фильтр-чип (активный — медный). onClick опционален (пока фильтры декоративны).
export function Chip({
  active,
  children,
  onClick,
}: {
  active?: boolean
  children: ReactNode
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-pill border px-3 py-1 text-[12px] transition-colors',
        active
          ? 'border-copper/40 bg-copper/10 text-copper'
          : 'border-line bg-card text-fog hover:text-mist',
      )}
    >
      {children}
    </button>
  )
}

// Мини-полоса просадки: value 0..100 (% глубины к тормозам).
export function MiniDd({ value }: { value: number }) {
  return (
    <span className="mini-dd">
      <i style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </span>
  )
}
