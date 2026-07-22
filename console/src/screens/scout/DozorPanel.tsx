import { type CSSProperties, type ReactNode, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  getDozorJournal,
  putDozorSettings,
  type DozorJournalEntry,
  type DozorSettings,
} from '@/lib/api'
import {
  AGE_OPTS,
  ageLabel,
  applyPreset,
  diffCount,
  fmtTurnover,
  type Preset,
  previewHint,
  sliderToSpread,
  sliderToTurnover,
  spreadToSlider,
  turnoverToSlider,
} from '@/lib/dozor'

// Рояль настроек дозора (макет dozor-knobs-mockup «Кого отбираем», группа 1). Выезжает гармошкой под
// плашкой. Пресеты + 7 крутилок (возраст/оборот/спред/скор/история/вселенная/список) → кнопка
// «Подтвердить для <бот>» (вариант А единой Разведки: называет бота — защита от правки не того
// инстанса; PUT desired в ядро → команда dozor_apply → мягкий рестарт скаута ~6 мин) + журнал.
export function DozorPanel({
  instanceId,
  botName,
  live,
  open,
  onApplied,
}: {
  instanceId: string
  botName: string
  live: DozorSettings
  open: boolean
  onApplied: () => void
}) {
  const [draft, setDraft] = useState<DozorSettings>(live)
  const [preset, setPreset] = useState<Preset | null>('live')
  const [busy, setBusy] = useState(false)
  const [journal, setJournal] = useState<DozorJournalEntry[]>([])

  // живые настройки сменились (инстанс / после применения) → сбрасываем черновик на живое
  useEffect(() => {
    setDraft(live)
    setPreset('live')
  }, [live])

  // журнал тянем при открытии рояля
  useEffect(() => {
    if (!open) return
    getDozorJournal(instanceId)
      .then(setJournal)
      .catch(() => setJournal([]))
  }, [open, instanceId])

  const diff = diffCount(draft, live)
  const set = (patch: Partial<DozorSettings>) => {
    setDraft((d) => ({ ...d, ...patch }))
    setPreset(null) // ручная правка — ни один пресет не активен
  }
  const pick = (p: Preset) => {
    setPreset(p)
    setDraft(applyPreset(p, live))
  }
  const changed = (k: keyof DozorSettings) => draft[k] !== live[k]

  const apply = async () => {
    if (diff === 0 || busy) return
    setBusy(true)
    try {
      await putDozorSettings(instanceId, draft)
      onApplied() // перечитает живые (apply=queued) → useEffect сбросит черновик
      getDozorJournal(instanceId)
        .then(setJournal)
        .catch(() => {})
    } finally {
      setBusy(false)
    }
  }

  const presets: [Preset, string][] = [
    ['live', 'Как сейчас'],
    ['strict', 'Строгий отбор'],
    ['wide', 'Широкий обзор'],
  ]

  return (
    <div
      className={`overflow-hidden transition-[max-height] duration-300 ${
        open ? 'mb-3 max-h-[1100px]' : 'max-h-0'
      }`}
    >
      <div className="rounded-card border border-line bg-card p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {presets.map(([p, l]) => (
            <button
              key={p}
              onClick={() => pick(p)}
              className={`rounded-card border px-3 py-1.5 text-[12px] transition-colors ${
                preset === p
                  ? 'border-copper text-copper'
                  : 'border-line bg-panel text-mist hover:border-steel'
              }`}
            >
              {l}
            </button>
          ))}
        </div>

        <Knob
          label="Возраст монеты"
          hint="строже = меньше мусора, мимо молодых ракет"
          changed={changed('min_age_days')}
          live={ageLabel(live.min_age_days)}
          onReset={() => set({ min_age_days: live.min_age_days })}
        >
          <div className="inline-flex overflow-hidden rounded-card border border-line">
            {AGE_OPTS.map((o) => (
              <button
                key={o.d}
                onClick={() => set({ min_age_days: o.d })}
                className={`border-r border-line px-3 py-1.5 text-[12.5px] last:border-r-0 ${
                  draft.min_age_days === o.d ? 'bg-floating text-copper' : 'bg-panel text-fog'
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </Knob>

        <Knob
          label="Оборот за сутки, от"
          hint="шкала логарифмическая: $1М → $500М"
          changed={changed('min_turnover_usd')}
          live={fmtTurnover(live.min_turnover_usd)}
          onReset={() => set({ min_turnover_usd: live.min_turnover_usd })}
        >
          <Slider
            value={turnoverToSlider(draft.min_turnover_usd)}
            min={0}
            max={100}
            onChange={(v) => set({ min_turnover_usd: sliderToTurnover(v) })}
            display={fmtTurnover(draft.min_turnover_usd)}
          />
        </Knob>

        <Knob
          label="Спред, до"
          hint="цена входа-выхода: уже = честнее исполнение"
          changed={changed('max_spread_pct')}
          live={`${live.max_spread_pct.toFixed(2)}%`}
          onReset={() => set({ max_spread_pct: live.max_spread_pct })}
        >
          <Slider
            value={spreadToSlider(draft.max_spread_pct)}
            min={3}
            max={30}
            onChange={(v) => set({ max_spread_pct: sliderToSpread(v) })}
            display={`${draft.max_spread_pct.toFixed(2)}%`}
          />
        </Knob>

        <Knob
          label="Проходной скор, от"
          hint="выше = элитнее и короче список"
          changed={changed('min_score')}
          live={String(live.min_score)}
          onReset={() => set({ min_score: live.min_score })}
        >
          <Slider
            value={draft.min_score}
            min={0}
            max={100}
            onChange={(v) => set({ min_score: v })}
            display={String(draft.min_score)}
          />
        </Knob>

        <NumKnob
          label="История торгов, от"
          unit="баров"
          hint="меньше — нечего анализировать"
          value={draft.min_history_bars}
          changed={changed('min_history_bars')}
          live={String(live.min_history_bars)}
          onChange={(v) => set({ min_history_bars: v })}
          onReset={() => set({ min_history_bars: live.min_history_bars })}
        />
        <NumKnob
          label="Вселенная оценки"
          unit="монет (топ по обороту)"
          hint="скольким монетам тянем свечи на утренней калибровке"
          value={draft.universe_max}
          changed={changed('universe_max')}
          live={String(live.universe_max)}
          onChange={(v) => set({ universe_max: v })}
          onReset={() => set({ universe_max: live.universe_max })}
        />
        <NumKnob
          label="Рабочий список дозора"
          unit="монет"
          hint="сколько лучших по скору сканируем на каждом баре"
          value={draft.list_max}
          changed={changed('list_max')}
          live={String(live.list_max)}
          onChange={(v) => set({ list_max: v })}
          onReset={() => set({ list_max: live.list_max })}
          last
        />

        <div className="mt-3 flex items-center gap-3 rounded-card border border-[#33291a] bg-[#15130f] px-3.5 py-2.5">
          <span className="whitespace-nowrap font-serif text-[16px] text-copper">
            {previewHint(draft, live)}
          </span>
          <span className="text-[11.5px] leading-snug text-fog">
            Прикидка по строгости фильтров. Точное «сколько монет пройдёт» появится с эндпоинтом
            счётчика калибровки (на согласовании).
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={apply} disabled={diff === 0 || busy}>
            {busy ? 'Применяю…' : `Подтвердить для ${botName} · пересбор ~6 мин`}
          </Button>
          <span className="text-[11.5px] text-ash">
            {diff === 0
              ? 'измени что-нибудь — кнопка оживёт'
              : `отличий: ${diff} · дозор мягко перезапустится и пересоберёт список`}
          </span>
        </div>
        {journal.length > 0 && (
          <div className="mt-2 text-[11.5px] text-ash">журнал: {fmtEntry(journal[0])}</div>
        )}
      </div>
    </div>
  )
}

// ── строка-крутилка (макет): подпись+подсказка | контрол | живое+сброс ────────────────────────────
function Knob({
  label,
  hint,
  changed,
  live,
  onReset,
  children,
  last,
}: {
  label: string
  hint?: string
  changed: boolean
  live: string
  onReset: () => void
  children: ReactNode
  last?: boolean
}) {
  return (
    <div
      className={`grid grid-cols-[minmax(160px,220px)_1fr_minmax(120px,150px)] items-center gap-3 py-2.5 ${
        last ? '' : 'border-b border-dashed border-[#17181d]'
      } ${changed ? 'rounded-card bg-gradient-to-r from-copper/[0.06] to-transparent' : ''}`}
    >
      <div>
        <div className="text-[13px] text-silver">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-ash">{hint}</div>}
      </div>
      <div>{children}</div>
      <div className="text-right text-[11px] text-ash">
        <span className="text-fog">живое: {live}</span>
        {changed && (
          <button
            onClick={onReset}
            title="вернуть живое"
            className="ml-1.5 rounded border border-line px-1.5 text-ash hover:text-fog"
          >
            ↺
          </button>
        )}
      </div>
    </div>
  )
}

function Slider({
  value,
  min,
  max,
  onChange,
  display,
}: {
  value: number
  min: number
  max: number
  onChange: (v: number) => void
  display: string
}) {
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ '--pct': `${pct}%` } as CSSProperties}
        className="range flex-1"
      />
      <span className="min-w-[80px] text-right text-[13.5px] text-silver tnum">{display}</span>
    </div>
  )
}

function NumKnob({
  label,
  unit,
  hint,
  value,
  changed,
  live,
  onChange,
  onReset,
  last,
}: {
  label: string
  unit: string
  hint?: string
  value: number
  changed: boolean
  live: string
  onChange: (v: number) => void
  onReset: () => void
  last?: boolean
}) {
  return (
    <Knob label={label} hint={hint} changed={changed} live={live} onReset={onReset} last={last}>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
          className="w-[92px] rounded-card border border-line bg-panel px-2 py-1.5 text-right text-[13.5px] text-bone tnum"
        />
        <span className="text-[12px] text-ash">{unit}</span>
      </div>
    </Knob>
  )
}

// журнал: «12:40 — скор 30→35 (актёр)» из before/after аудита (что реально изменилось)
function fmtEntry(e: DozorJournalEntry): string {
  const when = e.ts ? new Date(e.ts).toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '—'
  const changes: string[] = []
  for (const k of Object.keys(e.after ?? {})) {
    const a = (e.before ?? {})[k]
    const b = (e.after ?? {})[k]
    if (JSON.stringify(a) !== JSON.stringify(b)) changes.push(`${short(k)} ${fmtVal(k, a)}→${fmtVal(k, b)}`)
  }
  const who = e.actor ? ` (${e.actor.slice(0, 8)})` : ''
  return `${when} — ${changes.slice(0, 3).join(', ') || 'изменение'}${changes.length > 3 ? '…' : ''}${who}`
}
const _SHORT: Record<string, string> = {
  min_age_days: 'возраст',
  min_turnover_usd: 'оборот',
  max_spread_pct: 'спред',
  min_history_bars: 'история',
  min_score: 'скор',
  universe_max: 'вселенная',
  list_max: 'список',
  primary_tf: 'автоскан',
  tfs: 'ТФ',
}
const short = (k: string) => _SHORT[k] ?? k
function fmtVal(k: string, v: unknown): string {
  if (k === 'min_turnover_usd' && typeof v === 'number') return fmtTurnover(v)
  if (Array.isArray(v)) return v.join('+')
  return String(v)
}
