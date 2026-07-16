import { type ScoutSnapshot } from '@/lib/api'
import { isStale, scanAgeMinutes } from '@/lib/scout'

const ageText = (min: number): string =>
  min < 1 ? 'только что' : min < 60 ? `${Math.round(min)} мин назад` : `${(min / 60).toFixed(1)} ч назад`

// (в) «чей скаут» — ADR-0016 в.6 (режим представителя): ВСЕГДА видна на экране.
export function ProducerLabel({ producer }: { producer: string }) {
  return (
    <span className="text-[12px] text-fog">
      уровни от скаута: <b className="text-mist">{producer}</b>
    </span>
  )
}

// (а) возраст снимка «скан N назад»; при протухании (>2 сигн. баров) — жёлтая «данные устарели».
export function StaleBadge({ snap, now }: { snap: ScoutSnapshot; now?: number }) {
  const stale = isStale(snap, now)
  const age = ageText(scanAgeMinutes(snap, now))
  return (
    <span
      className={`rounded-pill border px-2 py-0.5 text-[11px] ${
        stale ? 'border-gold/40 bg-gold/10 text-gold' : 'border-line bg-card text-ash'
      }`}
      title={`scan_ts: ${snap.scan_ts}`}
    >
      {stale ? `⚠ данные устарели · скан ${age}` : `скан ${age}`}
    </span>
  )
}

// (б) config_mismatch.flag → красная плашка «другой конфиг» + details в тултипе.
export function MismatchBadge({ snap }: { snap: ScoutSnapshot }) {
  if (!snap.config_mismatch?.flag) return null
  const details = JSON.stringify(snap.config_mismatch.details ?? {}, null, 0)
  return (
    <span
      className="rounded-pill border border-danger/40 bg-danger/10 px-2 py-0.5 text-[11px] text-danger"
      title={`разошлись крутилки: ${details}`}
    >
      ⚠ разведка посчитана с другим конфигом
    </span>
  )
}

// (г) дисклеймер риска №2 вердикта — в деталь-вью, мелко.
export function Disclaimer() {
  return (
    <p className="text-[11px] leading-snug text-ash">
      Трекинг сетапов по 4h-барам; исполнение бота — на 15m. Статусы разведки и факт могут кратко
      расходиться (ADR-0016). Консоль показывает СНИМОК скаута, не живой тик цены.
    </p>
  )
}
