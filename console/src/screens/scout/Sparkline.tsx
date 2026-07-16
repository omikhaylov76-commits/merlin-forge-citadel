import { type ScoutKline } from '@/lib/api'

// Мини-спарклайн из klines снимка (close) + зона входа (полоса entry_0382..entry_0618).
export function Sparkline({
  klines,
  entryHi,
  entryLo,
}: {
  klines?: ScoutKline[]
  entryHi?: number
  entryLo?: number
}) {
  if (!klines || klines.length < 2) return <div className="h-7 w-[120px]" />
  const closes = klines.map((k) => k.c)
  const lo = Math.min(...closes, entryLo ?? Infinity)
  const hi = Math.max(...closes, entryHi ?? -Infinity)
  const W = 120
  const H = 28
  const pad = 2
  const x = (i: number) => pad + (i / (closes.length - 1)) * (W - 2 * pad)
  const y = (v: number) => (hi === lo ? H / 2 : pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad))
  const pts = closes.map((c, i) => `${x(i).toFixed(1)},${y(c).toFixed(1)}`).join(' ')
  const zone = entryHi != null && entryLo != null
  return (
    <svg width={W} height={H} className="block" aria-hidden>
      {zone && (
        <rect
          x={0}
          y={Math.min(y(entryHi), y(entryLo))}
          width={W}
          height={Math.abs(y(entryLo) - y(entryHi)) || 1}
          className="fill-current text-copper"
          opacity={0.12}
        />
      )}
      <polyline points={pts} fill="none" className="stroke-current text-fog" strokeWidth={1} />
    </svg>
  )
}
