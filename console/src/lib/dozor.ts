// Разведка-стол: домен настроек дозора для плашки/рояля. Зеркало SCOUT_DEFAULTS ядра + логика макета
// dozor-knobs-mockup (лог-шкала оборота, сегменты возраста, пресеты, сводка плашки). Консоль =
// дисплей+редактор desired; истина и применение — ядро (Q4). Числа не выдумываем (закон дисплея #32).
import type { DozorSettings } from './api'

// ── шкала оборота: логарифм $1М → $500М (макет turnUSD) ──────────────────────────────────────────
export const TURN_LO = 1_000_000
export const TURN_HI = 500_000_000
export const turnoverToSlider = (usd: number) =>
  Math.max(
    0,
    Math.min(100, Math.round((100 * Math.log(usd / TURN_LO)) / Math.log(TURN_HI / TURN_LO))),
  )
export const sliderToTurnover = (p: number) =>
  Math.round(TURN_LO * Math.pow(TURN_HI / TURN_LO, p / 100))
export const fmtTurnover = (usd: number) =>
  usd >= 1_000_000
    ? `$${(usd / 1_000_000).toFixed(usd < 3_000_000 ? 1 : 0)} млн`
    : `$${Math.round(usd / 1000)}к`

// ── возраст: сегменты (макет) ────────────────────────────────────────────────────────────────────
export const AGE_OPTS: { d: number; label: string }[] = [
  { d: 90, label: '3 мес' },
  { d: 180, label: '6 мес' },
  { d: 365, label: '1 год' },
  { d: 1095, label: '3 года' },
]
export const ageLabel = (days: number) => AGE_OPTS.find((o) => o.d === days)?.label ?? `${days} дн`

// max_spread_pct ↔ слайдер (единицы 0.01%): 0.15 ⇄ 15
export const spreadToSlider = (pct: number) => Math.round(pct * 100)
export const sliderToSpread = (v: number) => Math.round(v) / 100

// ── пресеты (макет preset): позиции слайдеров → реальные значения; 'live' = текущие живые ─────────
export type Preset = 'live' | 'strict' | 'wide'
export function applyPreset(p: Preset, live: DozorSettings): DozorSettings {
  if (p === 'strict')
    return {
      ...live,
      min_age_days: 365,
      min_turnover_usd: sliderToTurnover(52),
      max_spread_pct: 0.1,
      min_history_bars: 300,
      min_score: 50,
      universe_max: 300,
      list_max: 30,
    }
  if (p === 'wide')
    return {
      ...live,
      min_age_days: 90,
      min_turnover_usd: sliderToTurnover(17),
      max_spread_pct: 0.2,
      min_history_bars: 200,
      min_score: 25,
      universe_max: 500,
      list_max: 100,
    }
  return { ...live }
}

// Крутилки группы 1, которые правит Оператор (экспертные 5 — fresh/scan/cal/cal_hour/rps — идут как есть).
export const EDITED_KEYS: (keyof DozorSettings)[] = [
  'min_age_days',
  'min_turnover_usd',
  'max_spread_pct',
  'min_history_bars',
  'min_score',
  'universe_max',
  'list_max',
]
export const diffCount = (draft: DozorSettings, live: DozorSettings) =>
  EDITED_KEYS.filter((k) => draft[k] !== live[k]).length

// ── сводка для плашки (макет): ≥6 мес · ≥$5М/сут · скор ≥35 · список 50 · ТФ 4h+1h · автоскан … ───
export type StripPart = { pre: string; b: string; post?: string }
export function stripParts(s: DozorSettings): StripPart[] {
  return [
    { pre: '≥', b: ageLabel(s.min_age_days) },
    { pre: '≥', b: fmtTurnover(s.min_turnover_usd), post: '/сут' },
    { pre: 'скор ≥', b: String(s.min_score) },
    { pre: 'список ', b: String(s.list_max) },
    { pre: 'ТФ ', b: s.tfs.join('+') },
    { pre: 'автоскан ', b: s.primary_tf === '1h' ? 'каждый час' : 'каждые 4 часа' },
  ]
}

// ── превью «строгости» (честная директива, не выдуманное число): куда поедет список ──────────────
// Абсолютную прикидку «57 → N» строим позже — нужен readout счётчика калибровки (флаг Куратору).
function strictness(s: DozorSettings): number {
  return (
    s.min_score +
    s.min_turnover_usd / 1e6 +
    s.min_age_days / 30 +
    s.min_history_bars / 50 -
    s.max_spread_pct * 20 -
    s.universe_max / 50 -
    s.list_max / 5
  )
}
export function previewHint(draft: DozorSettings, live: DozorSettings): string {
  const d = strictness(draft) - strictness(live)
  if (Math.abs(d) < 1) return 'список ≈ как сейчас'
  return d > 0 ? 'список сузится ▾' : 'список расширится ▴'
}

// «скан N назад» (макет): свежесть последнего снимка скаута; на фронте, честно подписано (ADR-0001).
export function fmtAgo(iso?: string): string {
  if (!iso) return '—'
  const ms = Date.now() - Date.parse(iso)
  if (Number.isNaN(ms)) return '—'
  const min = Math.round(ms / 60000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const h = min / 60
  return `${h < 10 ? h.toFixed(1) : Math.round(h)} ч назад`
}
