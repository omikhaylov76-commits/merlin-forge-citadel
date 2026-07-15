import { useMemo, useState } from 'react'
import { PageHead } from '@/components/ui/page'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { KNOB_CATEGORIES, ETALON, ALL_KNOBS, type Knob, type KnobValue } from '@/lib/knobs'

const fmt = (v: KnobValue) => (typeof v === 'boolean' ? (v ? 'вкл' : 'выкл') : String(v))

function pluralKnob(n: number) {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return 'крутилка'
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'крутилки'
  return 'крутилок'
}

// Конструктор профиля (Кузница) — ПОЛНАЯ глубина: 23 крутилки движка (реестр lib/knobs), полки
// осн./эксп., ⚠-опасные (вне честных чисел → OOS протух), счётчик отличий от эталона, OOS-паспорт.
// Старт от «Малыша Мерлина» (клонируй-не-редактируй). Логика движка — read-only в ядре/картридже (#32).
export function Constructor() {
  const [expert, setExpert] = useState(false)
  const [values, setValues] = useState<Record<string, KnobValue>>(() => ({ ...ETALON }))
  const set = (k: string, v: KnobValue) => setValues((s) => ({ ...s, [k]: v }))
  const diff = useMemo(() => ALL_KNOBS.filter((k) => values[k.key] !== ETALON[k.key]), [values])
  const stale = diff.length > 0

  return (
    <div className="mx-auto max-w-[1216px]">
      <PageHead
        eyebrow="Кузница"
        title="Конструктор профиля"
        desc={`старт от эталона «Малыш Мерлин» · отличий от эталона: ${diff.length}`}
        action={
          <div className="flex items-center gap-3">
            {stale && (
              <Button variant="ghost" size="sm" onClick={() => setValues({ ...ETALON })}>
                Сбросить всё
              </Button>
            )}
            <label className="flex cursor-pointer select-none items-center gap-2 text-[12px] text-fog">
              Экспертный режим
              <Switch checked={expert} onChange={setExpert} />
            </label>
          </div>
        }
      />

      {!expert && (
        <div className="mb-4 rounded-card border border-line bg-card px-4 py-2 text-[12px] text-ash">
          Экспертные крутилки скрыты. <span className="text-copper">⚠</span> у крутилки — выход за честно
          оттестированные числа: паспорт протухнет, нужен новый OOS.
        </div>
      )}

      <div className="flex flex-col gap-4">
        {KNOB_CATEGORIES.map((cat) => {
          const shown = cat.knobs.filter((k) => expert || k.shelf === 'basic')
          const hidden = cat.knobs.length - shown.length
          if (shown.length === 0) return null
          return (
            <Card key={cat.title}>
              <CardHeader>
                <CardTitle>{cat.title}</CardTitle>
                <span className="text-[12px] text-ash">
                  {cat.knobs.length} {pluralKnob(cat.knobs.length)}
                  {hidden > 0 && !expert ? ` · ${hidden} экспертных скрыто` : ''}
                </span>
              </CardHeader>
              <div className="flex flex-col divide-y divide-line">
                {shown.map((k) => (
                  <KnobRow
                    key={k.key}
                    knob={k}
                    value={values[k.key]}
                    changed={values[k.key] !== ETALON[k.key]}
                    onChange={(v) => set(k.key, v)}
                    onReset={() => set(k.key, ETALON[k.key])}
                  />
                ))}
              </div>
            </Card>
          )
        })}

        <Card>
          <CardHeader>
            <CardTitle>Паспорт · OOS-бэктест</CardTitle>
            <span className="text-[12px] text-copper">Закон Кузницы</span>
          </CardHeader>
          {stale && (
            <div className="mb-3 rounded-card border border-copper/30 bg-copper/5 px-3 py-2 text-[12px] text-copper">
              Конфигурация изменена ({diff.length}) → паспорт протух. Перегони OOS перед развёртыванием.
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ['Calmar', '—'],
              ['Просадка', '—'],
              ['Сделок', '—'],
              ['Статус', 'нет прогона'],
            ].map(([k, v]) => (
              <div key={k} className="rounded-card border border-line bg-panel px-4 py-3 text-center">
                <div className="font-serif text-[20px] text-bone">{v}</div>
                <div className="mt-0.5 text-[11px] text-ash">{k}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 text-[12px] text-fog">
            Сдан = walk-forward + Calmar ≈ 2.0 + bootstrap worst-DD + режим-2022 + малый разрыв
            train→test. Черновик без паспорта не разворачивается.
          </div>
          <Button variant="primary" className="mt-3">
            ▶ Прогнать OOS
          </Button>
        </Card>
      </div>
    </div>
  )
}

function KnobRow({
  knob,
  value,
  changed,
  onChange,
  onReset,
}: {
  knob: Knob
  value: KnobValue
  changed: boolean
  onChange: (v: KnobValue) => void
  onReset: () => void
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-silver">
          {knob.label}
          {knob.danger && (
            <span className="text-copper" title="вне честно оттестированных чисел → новый OOS">
              ⚠
            </span>
          )}
          {knob.shelf === 'expert' && <Badge tone="neutral">эксп</Badge>}
        </div>
        <div className="text-[11px] text-ash">
          эталон: {fmt(knob.etalon)}
          {knob.hint ? ` · ${knob.hint}` : ''}
        </div>
      </div>
      {changed && (
        <button onClick={onReset} className="shrink-0 text-[11px] text-copper hover:underline">
          вернуть
        </button>
      )}
      <Control knob={knob} value={value} onChange={onChange} />
    </div>
  )
}

function Control({
  knob,
  value,
  onChange,
}: {
  knob: Knob
  value: KnobValue
  onChange: (v: KnobValue) => void
}) {
  if (knob.type === 'toggle') {
    return <Switch checked={Boolean(value)} onChange={onChange} />
  }
  if (knob.type === 'select') {
    return (
      <select
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-pill border border-line bg-panel px-3 py-1 text-[13px] text-bone focus:border-copper/50 focus:outline-none"
      >
        {knob.options!.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    )
  }
  return (
    <input
      type="number"
      value={value as number}
      min={knob.min}
      max={knob.max}
      step={knob.step}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      className="w-24 rounded-pill border border-line bg-panel px-3 py-1 text-right text-[13px] tnum text-bone focus:border-copper/50 focus:outline-none"
    />
  )
}
