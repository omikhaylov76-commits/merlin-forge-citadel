import { useMemo, useState, type ReactNode } from 'react'
import { PageHead } from '@/components/ui/page'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/cn'
import {
  KNOB_CATEGORIES,
  ETALON,
  ALL_KNOBS,
  UNIVERSE_COINS,
  ENGINE_LOGIC,
  type Knob,
  type KnobCategory,
  type KnobValue,
} from '@/lib/knobs'

const fmt = (v: KnobValue) => (typeof v === 'boolean' ? (v ? 'вкл' : 'выкл') : String(v))

function pluralKnob(n: number) {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return 'крутилка'
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'крутилки'
  return 'крутилок'
}

// ── метки зрелости (единый визуальный язык, #35) ────────────────────────────────
// 🟢 живое (крутится+сохраняется) · 🔵 из движка read-only (реальные значения, правка недоступна)
// · 🟣 в разработке · движок Ф5 (предпросмотр: контролы видимы, но disabled). Cool-тона = «движок/будущее».
const MATURITY = {
  live: { emoji: '🟢', label: 'живое', cls: 'border-ok/40 bg-ok/10 text-ok' },
  readonly: { emoji: '🔵', label: 'из движка · read-only', cls: 'border-[#5f74a0]/45 bg-[#5f74a0]/12 text-[#96a8cd]' },
  planned: { emoji: '🟣', label: 'в разработке · движок (Ф5)', cls: 'border-[#7d6ba8]/45 bg-[#7d6ba8]/12 text-[#ac98d5]' },
} as const

function Maturity({ t }: { t: keyof typeof MATURITY }) {
  const m = MATURITY[t]
  return (
    <span className={cn('inline-flex items-center gap-1 whitespace-nowrap rounded-pill border px-2 py-0.5 text-[10px]', m.cls)}>
      {m.emoji} {m.label}
    </span>
  )
}

const PLAN_TIP = 'планируется, движок в доработке (Ф5)'
const disCls = 'cursor-not-allowed opacity-55'
const inCls = 'rounded-pill border border-line bg-panel px-3 py-1 text-[13px] text-bone'

// Конструктор профиля (Кузница) — ПОЛНАЯ глубина (7 разделов, #35 по constructor-skeleton):
// 1–4 Риск/Капитал/Исполнение/Режимы (🟢 крутилки) · 5 Вселенная (🔵 монеты + 🟣 скринер) ·
// 6 Политика входа (🟣) · 7 Служебные (🟢) · Зафиксированная логика (🔵) · OOS-паспорт.
// Консоль собирает конфиг; логика движка read-only в ядре/картридже (ADR-0001/#32). Всё на фикстурах.
export function Constructor() {
  const [expert, setExpert] = useState(false)
  const [values, setValues] = useState<Record<string, KnobValue>>(() => ({ ...ETALON }))
  const set = (k: string, v: KnobValue) => setValues((s) => ({ ...s, [k]: v }))
  const diff = useMemo(() => ALL_KNOBS.filter((k) => values[k.key] !== ETALON[k.key]), [values])
  const stale = diff.length > 0

  const catProps = { expert, values, set }
  return (
    <div className="mx-auto max-w-[1880px]">
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

      {/* легенда меток зрелости */}
      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-card border border-line bg-card px-4 py-2 text-[12px] text-ash">
        <span>Зрелость:</span>
        <Maturity t="live" />
        <Maturity t="readonly" />
        <Maturity t="planned" />
        {!expert && <span className="ml-1">· экспертные крутилки скрыты · ⚠ = вне честных чисел (новый OOS)</span>}
      </div>

      <div className="flex flex-col gap-4">
        {/* разделы 1–4: крутилки 🟢 */}
        {KNOB_CATEGORIES.slice(0, 4).map((cat) => (
          <KnobCategoryCard key={cat.title} cat={cat} {...catProps} />
        ))}

        {/* раздел 5 · Вселенная */}
        <Universe />

        {/* раздел 6 · Политика входа */}
        <EntryPolicy />

        {/* раздел 7 · Служебные 🟢 */}
        <KnobCategoryCard cat={KNOB_CATEGORIES[4]} {...catProps} />

        {/* зафиксированная логика движка 🔵 */}
        <EngineLogic />

        {/* OOS-паспорт */}
        <Passport diff={diff.length} stale={stale} />
      </div>
    </div>
  )
}

// ── разделы 1–4, 7: крутилки (🟢) ────────────────────────────────────────────────
function KnobCategoryCard({
  cat,
  expert,
  values,
  set,
}: {
  cat: KnobCategory
  expert: boolean
  values: Record<string, KnobValue>
  set: (k: string, v: KnobValue) => void
}) {
  const shown = cat.knobs.filter((k) => expert || k.shelf === 'basic')
  const hidden = cat.knobs.length - shown.length
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>{cat.title}</CardTitle>
          <Maturity t="live" />
        </div>
        <span className="text-[12px] text-ash">
          {cat.knobs.length} {pluralKnob(cat.knobs.length)}
          {hidden > 0 && !expert ? ` · ${hidden} экспертных скрыто` : ''}
        </span>
      </CardHeader>
      {shown.length === 0 ? (
        <div className="text-[12px] text-ash">
          Все крутилки раздела — экспертные. Включите «Экспертный режим», чтобы показать.
        </div>
      ) : (
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
      )}
    </Card>
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

function Control({ knob, value, onChange }: { knob: Knob; value: KnobValue; onChange: (v: KnobValue) => void }) {
  if (knob.type === 'toggle') return <Switch checked={Boolean(value)} onChange={onChange} />
  if (knob.type === 'select') {
    return (
      <select
        value={String(value)}
        onChange={(e) => onChange(e.target.value)}
        className={cn(inCls, 'focus:border-copper/50 focus:outline-none')}
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
      className={cn(inCls, 'w-24 text-right tnum focus:border-copper/50 focus:outline-none')}
    />
  )
}

// ── раздел 5 · Вселенная ──────────────────────────────────────────────────────────
function ModeBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-nav px-3 py-1 text-[12px] transition-colors',
        active ? 'bg-floating text-bone' : 'text-fog hover:text-mist',
      )}
    >
      {children}
    </button>
  )
}

function DisField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-ash">
      {label}
      {children}
    </label>
  )
}

function Universe() {
  const [mode, setMode] = useState<'fix' | 'dyn'>('fix')
  return (
    <Card>
      <CardHeader>
        <CardTitle>5 · Вселенная</CardTitle>
        <span className="text-[12px] text-ash">какие монеты торгует профиль</span>
      </CardHeader>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-[12px] text-fog">
        Режим капитала:
        <Badge tone="live">pool · текущий</Badge>
        <Maturity t="readonly" />
        <span className="mx-1 h-4 w-px bg-line" />
        <button disabled aria-disabled title={PLAN_TIP} className={cn(inCls, 'py-0.5 text-[12px]', disCls)}>
          per_coin
        </button>
        <Maturity t="planned" />
      </div>

      <div className="mb-3 flex gap-1">
        <ModeBtn active={mode === 'fix'} onClick={() => setMode('fix')}>
          Фикс-набор
        </ModeBtn>
        <ModeBtn active={mode === 'dyn'} onClick={() => setMode('dyn')}>
          Динамика из Разведки
        </ModeBtn>
      </div>

      {mode === 'fix' ? (
        <>
          <div className="mb-2 flex items-center gap-2">
            <h4 className="text-[13px] font-medium text-mist">Шаг 1 · Скринер</h4>
            <Maturity t="planned" />
          </div>
          <div className={cn('mb-4 flex flex-wrap items-end gap-3', disCls)}>
            <DisField label="Капитализация">
              <select disabled title={PLAN_TIP} className={inCls} defaultValue="Топ-100 (CMC)">
                <option>Топ-50 (CMC)</option>
                <option>Топ-100 (CMC)</option>
                <option>Топ-200 (CMC)</option>
              </select>
            </DisField>
            <DisField label="Возраст монеты">
              <select disabled title={PLAN_TIP} className={inCls} defaultValue="больше 6 месяцев">
                <option>больше 1 года</option>
                <option>больше 6 месяцев</option>
                <option>больше 3 месяцев</option>
              </select>
            </DisField>
            <DisField label="Оборот ≥, $">
              <input type="number" disabled title={PLAN_TIP} defaultValue={5000000} className={cn(inCls, 'w-32 text-right tnum')} />
            </DisField>
            <button disabled aria-disabled title={PLAN_TIP} className={cn(inCls, disCls)}>
              🔎 Подобрать монеты
            </button>
          </div>

          <div className="mb-2 flex flex-wrap items-center gap-2">
            <h4 className="text-[13px] font-medium text-mist">Шаг 2 · Набор монет ({UNIVERSE_COINS.length})</h4>
            <Maturity t="readonly" />
          </div>
          <div className="overflow-x-auto rounded-card border border-line">
            <table className="dt">
              <thead>
                <tr>
                  <th>Монета</th>
                  <th className="num">mb1, %</th>
                  <th className="num">mb2, %</th>
                  <th className="num">Плечо</th>
                  <th className="num">Вес, %</th>
                  <th>Вкл</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {UNIVERSE_COINS.map((c) => (
                  <tr key={c.sym}>
                    <td className="font-semibold text-bone">{c.sym}USDT</td>
                    <td className="num">{c.mb1.toFixed(1)}</td>
                    <td className="num">{c.mb2.toFixed(1)}</td>
                    <td className="num text-fog">{c.lev}×</td>
                    <td className="num text-fog">{c.weight}</td>
                    <td>
                      <span className="text-ok">✓</span>
                    </td>
                    <td>
                      <button disabled aria-disabled title={PLAN_TIP} className={cn('text-ash', disCls)}>
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 text-[11px] text-ash">
            Значения — эталон COINS_CONFIG @b75bd17 (демо). Правка/удаление монет и live-эндпоинт вселенной — TODO (Ф5/бэкенд).
          </div>
        </>
      ) : (
        <>
          <div className="mb-2 flex items-center gap-2">
            <h4 className="text-[13px] font-medium text-mist">Критерии динамического набора</h4>
            <Maturity t="planned" />
          </div>
          <div className={cn('flex flex-wrap items-end gap-3', disCls)}>
            <DisField label="Мин. скор ≥">
              <input type="number" disabled title={PLAN_TIP} defaultValue={35} className={cn(inCls, 'w-20 text-right tnum')} />
            </DisField>
            <DisField label="Капитализация">
              <select disabled title={PLAN_TIP} className={inCls} defaultValue="Топ-100">
                <option>Топ-50</option>
                <option>Топ-100</option>
                <option>Топ-300</option>
              </select>
            </DisField>
            <DisField label="Макс. монет">
              <input type="number" disabled title={PLAN_TIP} defaultValue={16} className={cn(inCls, 'w-20 text-right tnum')} />
            </DisField>
            <DisField label="Свежесть ≤, бар">
              <input type="number" disabled title={PLAN_TIP} defaultValue={72} className={cn(inCls, 'w-20 text-right tnum')} />
            </DisField>
          </div>
          <div className="mt-2 text-[11px] text-ash">
            Те же пороги, что в Разведке (скор/оборот/возраст/капа) — бот берёт монеты динамически. Планируется (движок в доработке).
          </div>
        </>
      )}
    </Card>
  )
}

// ── раздел 6 · Политика входа (🟣 весь раздел) ─────────────────────────────────────
const LEGS: { leg: string; take: boolean; dip: boolean }[] = [
  { leg: '0.382 (1-я)', take: false, dip: false },
  { leg: '0.5 (2-я)', take: true, dip: true },
  { leg: '0.618 (3-я)', take: false, dip: false },
]

function EntryPolicy() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>6 · Политика входа</CardTitle>
          <Maturity t="planned" />
        </div>
        <span className="text-[12px] text-ash">как бот заходит и выходит</span>
      </CardHeader>

      <div className="mb-3 rounded-card border border-line bg-panel px-3 py-2 text-[12px] text-fog">
        <b className="text-silver">Классика (сейчас):</b> заходим только в свежий сетап, который только
        отрисовался — ни одна нога ещё не отработала. Дальше движок ведёт по своим правилам.
      </div>

      <div className="mb-3 text-[12px] text-ash">
        Предпросмотр «ручного» входа — движок пока не выбирает ногу на входе, планируется (Ф5):
      </div>

      <div className={cn('mb-3 flex flex-wrap items-center gap-3 text-[12px] text-fog', disCls)}>
        Стадия:
        {['forming', 'tracking', 'ready', 'committed'].map((s) => (
          <label key={s} className="flex items-center gap-1">
            <input type="checkbox" disabled defaultChecked={s === 'ready'} title={PLAN_TIP} className="cursor-not-allowed" />
            {s}
          </label>
        ))}
        <label className="flex items-center gap-1">
          только свежее ≤
          <input type="number" disabled defaultValue={24} title={PLAN_TIP} className={cn(inCls, 'w-14 text-right tnum')} /> бар
        </label>
      </div>

      <div className="overflow-x-auto rounded-card border border-line">
        <table className="dt">
          <thead>
            <tr>
              <th>Нога (Fib)</th>
              <th>Брать</th>
              <th>Как входим</th>
              <th className="num">Допуск, %</th>
            </tr>
          </thead>
          <tbody>
            {LEGS.map((l) => (
              <tr key={l.leg}>
                <td className="text-silver">{l.leg}</td>
                <td>
                  <input type="checkbox" disabled defaultChecked={l.take} title={PLAN_TIP} className="cursor-not-allowed opacity-60" />
                </td>
                <td>
                  <select disabled title={PLAN_TIP} className={cn(inCls, disCls)} defaultValue={l.dip ? 'двойной заход' : 'обычный'}>
                    <option>обычный</option>
                    <option>двойной заход</option>
                  </select>
                </td>
                <td className="num">
                  <input type="number" disabled defaultValue={0.04} step={0.01} title={PLAN_TIP} className={cn(inCls, 'w-20 text-right tnum', disCls)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className={cn('mt-3 flex flex-wrap items-center gap-4 text-[12px] text-fog', disCls)}>
        Как выходим:
        <label className="flex items-center gap-1">
          <input type="radio" name="exit-preview" disabled defaultChecked title={PLAN_TIP} className="cursor-not-allowed" /> Трейлер (0.4R)
        </label>
        <label className="flex items-center gap-1">
          <input type="radio" name="exit-preview" disabled title={PLAN_TIP} className="cursor-not-allowed" /> Фикс. тейк-профит
        </label>
        <span>· стоп fib 1.0</span>
      </div>
      <div className="mt-2 text-[11px] text-ash">
        Весь раздел — визуальный предпросмотр замысла (per-нога матрица — отдельная сущность; крутилки
        DOUBLE_DIP из раздела 3 здесь не дублируются).
      </div>
    </Card>
  )
}

// ── зафиксированная логика движка (🔵 read-only) ────────────────────────────────────
function EngineLogic() {
  return (
    <Card className="border-[#5f74a0]/25">
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Зафиксированная логика движка</CardTitle>
          <Maturity t="readonly" />
        </div>
        <span className="text-[12px] text-ash">🔒 не настраивается</span>
      </CardHeader>
      <div className="flex flex-col divide-y divide-line">
        {ENGINE_LOGIC.map((l) => (
          <div key={l.label} className="py-2">
            <div className="text-[13px] text-silver">{l.label}</div>
            <div className="text-[12px] text-ash">{l.text}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-[11px] text-ash">Мозг движка — не настраивается, показано для прозрачности.</div>
    </Card>
  )
}

// ── OOS-паспорт ──────────────────────────────────────────────────────────────────
function Passport({ diff, stale }: { diff: number; stale: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Паспорт · OOS-бэктест</CardTitle>
        <span className="text-[12px] text-copper">Закон Кузницы</span>
      </CardHeader>
      {stale && (
        <div className="mb-3 rounded-card border border-copper/30 bg-copper/5 px-3 py-2 text-[12px] text-copper">
          Конфигурация изменена ({diff}) → паспорт протух. Перегони OOS перед развёртыванием.
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
        Сдан = walk-forward + Calmar ≈ 2.0 + bootstrap worst-DD + режим-2022 + малый разрыв train→test.
        Черновик без паспорта не разворачивается.
      </div>
      <Button variant="primary" className="mt-3">
        ▶ Прогнать OOS
      </Button>
    </Card>
  )
}
