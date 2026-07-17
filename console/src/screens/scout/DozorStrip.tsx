import { useState } from 'react'
import { scanNow, type DozorApply, type DozorSettings } from '@/lib/api'
import { fmtAgo, stripParts } from '@/lib/dozor'

// Плашка дозора (макет razvedka-page-layout): всегда видна, одна строка — сводка порогов + ⚙ настроить
// (тумблер рояля) + 🔎 сканировать сейчас (команда scan_now) + свежесть скана + счётчик Набора.
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

  // статус применения последней команды: применяется…/расхождение (макет части 1)
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
      // скаут заберёт команду (~25с) + Этап B (~60–100с) → освежаем доску несколько раз
      window.setTimeout(() => setScanning(false), 2500)
      window.setTimeout(onScanned, 30000)
      window.setTimeout(onScanned, 90000)
    } catch {
      setScanning(false)
    }
  }

  return (
    <div className="mb-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-card border border-line bg-card px-3 py-2">
      <span className="mr-0.5 text-[11px] uppercase tracking-wide text-ash">Дозор</span>
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-2.5">
          <span className="whitespace-nowrap text-[12.5px] text-fog">
            {p.pre}
            <b className="font-semibold text-silver">{p.b}</b>
            {p.post}
          </span>
          {i < parts.length - 1 && <span className="text-[#2a2c33]">·</span>}
        </span>
      ))}
      {applyMsg && (
        <span
          className={`text-[11px] ${applyMsg === 'расхождение' ? 'text-danger' : 'text-copper'}`}
        >
          {applyMsg}
        </span>
      )}

      <button
        onClick={onToggle}
        className={`ml-auto rounded-card border px-3 py-1.5 text-[12.5px] transition-colors ${
          open
            ? 'border-copper/50 bg-panel text-copper'
            : 'border-line bg-panel text-copper hover:border-copper/50'
        }`}
      >
        ⚙ Настроить
      </button>
      <button
        onClick={scan}
        disabled={scanning}
        className="rounded-card border border-[#3a3220] bg-gradient-to-b from-[#1d1712] to-[#171310] px-3.5 py-1.5 text-[12.5px] text-gold transition-opacity disabled:opacity-60"
      >
        {scanning ? '⟳ скан идёт…' : '🔎 Сканировать сейчас'}
      </button>
      <span className="text-[11.5px] text-ash">скан {fmtAgo(scanTs)}</span>
      {naborCount > 0 && (
        <span className="rounded-pill border border-line bg-panel px-2.5 py-1 text-[12px] text-gold">
          ★ Набор: {naborCount}
        </span>
      )}
    </div>
  )
}
