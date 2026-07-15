import { type ReactNode } from 'react'
import { cn } from '@/lib/cn'

// Единые состояния экрана (#32: каждый экран — пусто / грузится / ошибка).

export function Loading({ label = 'Загрузка…', className }: { label?: string; className?: string }) {
  return (
    <div className={cn('flex items-center gap-2 py-8 text-[13px] text-ash', className)}>
      <span className="h-3 w-3 animate-pulse rounded-full bg-copper/60" />
      {label}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  icon,
}: {
  title: string
  hint?: string
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      <div className="text-2xl text-steel">{icon ?? '◍'}</div>
      <div className="text-[14px] text-mist">{title}</div>
      {hint && <div className="max-w-sm text-[12px] text-ash">{hint}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-card border border-danger/30 bg-danger/5 p-4">
      <div className="text-[13px] font-medium text-danger">Не удалось загрузить</div>
      <div className="text-[12px] text-fog">{error.message}</div>
      {onRetry && (
        <button onClick={onRetry} className="mt-1 text-[12px] text-copper hover:underline">
          Повторить
        </button>
      )}
    </div>
  )
}
