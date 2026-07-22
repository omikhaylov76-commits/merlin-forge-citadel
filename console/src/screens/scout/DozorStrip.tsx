import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { scanNow, type DozorApply, type DozorSettings } from '@/lib/api'
import { fmtAgo, stripParts } from '@/lib/dozor'

// Строка дозора (макет razvedka-page-layout): лёгкая строка-метаданные под шапкой — «что ищем».
// Слева сводка порогов, справа управление: ⚙ рояль + 🔎 scan_now + свежесть + Набор.
// #3 (жалоба Оператора): скан/применение идут НА БОТЕ (сервер), не на странице — уход со страницы
// НЕ сбрасывает их. Индикатор «идёт» держим в localStorage (переживает навигацию) + честная подпись
// «можно уходить, результат появится сам» — чтобы не залипать на открытой странице впустую.
const SCAN_WINDOW_MS = 120_000 // окно «скан ещё идёт» (пересбор скаута ~1-2 мин)

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
  const parts = stripParts(settings)
  const scanKey = `mfc.scanAt.${instanceId}`
  const [scanAt, setScanAt] = useState<number | null>(null)
  const [, force] = useState(0) // тик обновления «идёт/погас», не завязан на данные

  // Синк индикатора из localStorage (переживает уход/возврат) + тик, пока скан свеж.
  useEffect(() => {
    const read = () => {
      const v = Number(localStorage.getItem(scanKey) || 0)
      setScanAt(v && Date.now() - v < SCAN_WINDOW_MS ? v : null)
    }
    read()
    const id = setInterval(() => {
      read()
      force((n) => (n + 1) % 1000)
    }, 5_000)
    return () => clearInterval(id)
  }, [scanKey])

  const scanRunning = scanAt != null && Date.now() - scanAt < SCAN_WINDOW_MS

  // Применение порогов («Подтвердить») идёт на боте ~6 мин, статус — серверный (переживает навигацию).
  const applyMsg =
    apply.status === 'queued' || apply.status === 'delivered'
      ? 'пороги применяются на боте ~6 мин · можно уходить'
      : apply.status === 'failed'
        ? 'расхождение'
        : null

  const scan = async () => {
    if (scanRunning) return
    try {
      await scanNow(instanceId)
      const now = Date.now()
      localStorage.setItem(scanKey, String(now)) // переживёт уход со страницы
      setScanAt(now)
      window.setTimeout(onScanned, 30_000) // подтянуть доску, когда результат долетит в ядро
      window.setTimeout(onScanned, 90_000)
    } catch {
      /* не прошло — кнопка остаётся активной */
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
        <span
          className={applyMsg === 'расхождение' ? 'text-[11px] text-danger' : 'text-[11px] text-copper'}
        >
          {applyMsg}
        </span>
      )}
      {/* #3: устойчивая метка скана — «идёт на боте, можно уходить» (не сбрасывается при навигации) */}
      {scanRunning && (
        <span
          className="rounded-pill border border-gold/30 bg-gold/5 px-2 py-0.5 text-[11px] text-gold"
          title="скан идёт на самом боте (в облаке), НЕ на этой странице. Можно уйти — доска обновится сама, когда результат долетит."
        >
          ⟳ скан идёт ~1-2 мин · можно уходить, результат появится сам
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        {scanTs && <span className="text-[11.5px] text-ash">скан {fmtAgo(scanTs)}</span>}
        {naborCount > 0 && (
          <span className="rounded-pill border border-line px-2.5 py-1 text-[11.5px] text-gold">
            ★ Набор: {naborCount}
          </span>
        )}
        <Button variant={open ? 'primary' : 'ghost'} size="sm" onClick={onToggle} aria-expanded={open}>
          ⚙ Настроить
        </Button>
        <Button
          size="sm"
          onClick={scan}
          disabled={scanRunning}
          className="border-gold/30 text-gold hover:border-gold/50"
        >
          {scanRunning ? '⟳ скан идёт…' : '🔎 Сканировать сейчас'}
        </Button>
      </div>
    </div>
  )
}
