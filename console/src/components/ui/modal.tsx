import { type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

// Модал подтверждения опасного действия (сквозное #34: danger = последствия В ЧИСЛАХ + «расписка»).
export function ConfirmModal({
  open,
  title,
  body,
  confirmLabel,
  tone = 'primary',
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  body: ReactNode
  confirmLabel: string
  tone?: 'primary' | 'danger'
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-md rounded-card border border-line bg-floating p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 text-[15px] font-semibold text-bone">{title}</div>
        <div className="mb-4 text-[13px] leading-relaxed text-fog">{body}</div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Отмена
          </Button>
          <Button variant={tone} size="sm" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
