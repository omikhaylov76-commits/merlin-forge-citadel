import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { scanNow, type DozorApply, type DozorSettings } from '@/lib/api'
import { fmtAgo, stripParts } from '@/lib/dozor'

// Строка дозора (макет razvedka-page-layout, посадка «в дизайн»): НЕ отдельная карточка (не конкурирует
// с доской), а лёгкая безбордюрная строка-метаданные под шапкой — «что ищем». Слева сводка порогов,
// справа управление: ⚙ рояль + 🔎 scan_now + свежесть + Набор. Чипы ниже — «что смотрим» (фильтр показа).
export function DozorStrip({
  instanceId,
  settings,
  apply,
  scanTs,
  naborCount,
  open,
  onToggle,
  onScanned,
}: {
  instanceId: string
  settings: DozorSettings
  apply: DozorApply
  scanTs?: string
  naborCount: number
  open: boolean
  onToggle: () => void
  onScanned: () => void
}) {
  const [scanning, setScanning] = useState(false)
  const parts = stripParts(settings)

  const applyMsg =
    apply.status === 'queued' || apply.status === 'delivered'
      ? 'применяется…'
      : apply.status === 'failed'
        ? 'расхождение'
        : null

  const scan = async () => {
    if (scanning) return
    setScanning(true)
    try {
      await scanNow(instanceId)
      window.setTimeout(() => setScanning(false), 2500)
      window.setTimeout(onScanned, 30000)
      window.setTimeout(onScanned, 90000)
    } catch {
      setScanning(false)
    }
  }

  return (
    <div
      className={`mb-3 flex flex-wrap items-center gap-x-2.5 gap-y-2 pb-3 ${
        open ? '' : 'border-b border-line/60'
      }`}
    >
      <span className="text-[11px] uppercase tracking-wider text-ash">Дозор</span>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[12.5px] text-fog">
        {parts.map((p, i) => (
          <span key={i} className="flex items-center gap-2.5">
            <span className="whitespace-nowrap">
              {p.pre}
              <b className="font-semibold text-silver">{p.b}</b>
              {p.post}
            </span>
            {i < parts.length - 1 && <span className="text-line">·</span>}
          </span>
        ))}
      </div>
      {applyMsg && (
        <span className={applyMsg === 'расхождение' ? 'text-[11px] text-danger' : 'text-[11px] text-copper'}>
          {applyMsg}
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        {scanTs && <span className="text-[11.5px] text-ash">скан {fmtAgo(scanTs)}</span>}
        {naborCount > 0 && (
          <span className="rounded-pill border border-line px-2.5 py-1 text-[11.5px] text-gold">
            ★ Набор: {naborCount}
          </span>
        )}
        <Button
          variant={open ? 'primary' : 'ghost'}
          size="sm"
          onClick={onToggle}
          aria-expanded={open}
        >
          ⚙ Настроить
        </Button>
        <Button
          size="sm"
          onClick={scan}
          disabled={scanning}
          className="border-gold/30 text-gold hover:border-gold/50"
        >
          {scanning ? '⟳ скан идёт…' : '🔎 Сканировать сейчас'}
        </Button>
      </div>
    </div>
  )
}
