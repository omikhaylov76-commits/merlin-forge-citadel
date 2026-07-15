import { cn } from '@/lib/cn'

// Тумблер «слаш» (вкл — медный). role=switch для доступности (WCAG).
export function Switch({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-pill border transition-colors',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-copper/60',
        checked ? 'border-copper/50 bg-copper/25' : 'border-line bg-floating',
      )}
    >
      <span
        className={cn(
          'inline-block h-3.5 w-3.5 rounded-full bg-bone transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        )}
      />
    </button>
  )
}
