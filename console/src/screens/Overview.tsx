import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loading, ErrorState, EmptyState } from '@/components/ui/states'
import { useAsync } from '@/lib/useAsync'
import { overviewFixture as ov } from '@/lib/fixtures'

const money = (n: number) => '$' + Math.round(n).toLocaleString('ru-RU')
const moneyK = (n: number) => '$' + (n / 1000).toFixed(1).replace('.', ',') + 'K'

// ── экран Обзор ───────────────────────────────────────────────────────────────
// v1: дисплей по макету. Агрегаты (AUM/P&L/капитал) — демо-фикстуры (деньги считает ядро, #32);
// «Требует внимания» показывает реальную машину состояний (грузится/пусто/ошибка/данные).
export function Overview() {
  return (
    <div className="mx-auto flex max-w-[1216px] flex-col gap-3">
      <Hero />
      <Kpis />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
        <CapitalCard />
        <AttentionCard />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <HealthCard />
        <FeedCard />
      </div>
    </div>
  )
}

function Hero() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 rounded-card border border-line bg-card px-6 py-4">
      <div>
        <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-widest text-ash">
          Флот · сводка
          <span className="rounded-pill border border-line px-1.5 py-0.5 text-[9px] normal-case tracking-normal text-steel">
            демо-данные
          </span>
        </div>
        <div className="gild font-serif text-[40px] leading-none tnum">{money(ov.aum)}</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[13px] text-fog">
          <span>Активы под управлением</span>
          <span className="text-ok">▲ {ov.aumDeltaPct}% за месяц</span>
          <Badge tone="gold">P&amp;L +{moneyK(ov.pnlNet)} net</Badge>
        </div>
      </div>
      <div className="flex gap-2.5">
        <Button variant="default">Собрать профиль</Button>
        <Button variant="primary">Развернуть бота</Button>
      </div>
    </div>
  )
}

function Kpi({
  label,
  value,
  sub,
  gild,
  accent,
  children,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  gild?: boolean
  accent?: boolean
  children?: React.ReactNode
}) {
  return (
    <Card className={`p-4 ${accent ? 'border-copper/30' : ''}`}>
      <div className="mb-1 text-[11px] uppercase tracking-widest text-ash">{label}</div>
      <div className={`font-serif text-[24px] leading-none tnum ${gild ? 'gild' : 'text-bone'}`}>
        {value}
      </div>
      {sub && <div className="mt-1 text-[12px] text-fog">{sub}</div>}
      {children}
    </Card>
  )
}

function Kpis() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Kpi label="Активы (AUM)" value={moneyK(ov.aum)} gild sub={<span className="text-ok">▲ {ov.aumDeltaPct}%</span>} />
      <Kpi
        label="Боты в работе"
        value={
          <>
            {ov.botsRunning}
            <span className="text-[15px] text-ash"> / {ov.botsTotal}</span>
          </>
        }
        sub={`${ov.botsPaused} на паузе`}
      />
      <Kpi label="P&L за период" value={<span className="text-ok">+{moneyK(ov.pnlNet)}</span>} sub="net, после издержек" />
      <Kpi
        label="К выставлению ◆"
        value={money(ov.toBill)}
        gild
        accent
        sub={`${ov.periodsToClose} периода к закрытию`}
      />
    </div>
  )
}

function EquityCurve({ points }: { points: number[] }) {
  const W = 640
  const H = 112
  const pad = 8
  const stepX = W / (points.length - 1)
  const y = (v: number) => H - pad - v * (H - pad * 2)
  const path = points.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = points[points.length - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" className="mt-1">
      <defs>
        <linearGradient id="ln" x1="0" x2="1">
          <stop offset="0" stopColor="#ae9357" />
          <stop offset=".42" stopColor="#fff0cc" />
          <stop offset=".72" stopColor="#ae9357" />
          <stop offset="1" stopColor="#bd9d4f" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="fl" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#cc9166" stopOpacity=".15" />
          <stop offset="1" stopColor="#cc9166" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => Math.round(H * f)).map((gy) => (
        <line key={gy} x1="0" y1={gy} x2={W} y2={gy} stroke="#141519" />
      ))}
      <path d={`${path} L${W},${H} L0,${H} Z`} fill="url(#fl)" />
      <path d={path} fill="none" stroke="url(#ln)" strokeWidth="2.3" strokeLinecap="round" />
      <circle cx={W} cy={y(last)} r="3.4" fill="#fff0cc" />
    </svg>
  )
}

function CapitalCard() {
  const periods = ['Д', 'Н', 'М', 'Кв', 'Всё']
  return (
    <Card className="p-4">
      <CardHeader>
        <CardTitle>Капитал флота</CardTitle>
        <div className="flex gap-1">
          {periods.map((p) => (
            <span
              key={p}
              className={`rounded-nav px-2 py-0.5 text-[11px] ${p === 'М' ? 'bg-floating text-bone' : 'text-ash'}`}
            >
              {p}
            </span>
          ))}
        </div>
      </CardHeader>
      <div className="gild font-serif text-[26px] tnum">{money(ov.aum)}</div>
      <div className="mb-1 mt-0.5 text-[12px] text-fog">
        +{money(ov.capitalDelta30d)} за 30 дней · просадка от пика {ov.drawdownFromPeak}%
      </div>
      <EquityCurve points={ov.equityCurve} />
    </Card>
  )
}

const dotColor: Record<string, string> = { k: 'bg-danger', a: 'bg-copper', p: 'bg-steel' }

function AttentionCard() {
  // реальная машина состояний (#32): пусто/грузится/ошибка/данные. Источник — фикстуры (демо);
  // при живом readout сюда встанет getStuckAccounts() без изменения разметки.
  const { loading, error, data, reload } = useAsync(() => Promise.resolve(ov.attention), [])
  return (
    <Card className="p-4">
      <CardHeader>
        <CardTitle>Требует внимания</CardTitle>
        <a className="cursor-pointer text-[12px] text-copper hover:underline">все →</a>
      </CardHeader>
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState title="Всё спокойно" hint="Нет застрявшего биллинга и тревог." icon="✓" />
      ) : (
        <div className="flex flex-col divide-y divide-line">
          {data.map((r, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <span className={`h-2 w-2 shrink-0 rounded-full ${dotColor[r.kind]}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-silver">{r.who}</div>
                <div className="truncate text-[11px] text-ash">{r.what}</div>
              </div>
              <span className="shrink-0 text-[11px] text-fog">{r.tag}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function HealthCard() {
  const h = ov.health
  return (
    <Card className="p-4">
      <CardHeader>
        <CardTitle>Здоровье флота · запас до тормозов</CardTitle>
        <span className="text-[12px] text-ash">худший: {h.worst}</span>
      </CardHeader>
      <div className="pt-1">
        <div className="relative h-2.5 w-full overflow-hidden rounded-pill bg-floating">
          <div
            className="absolute inset-y-0 left-0 rounded-pill bg-gradient-to-r from-copper to-danger"
            style={{ width: `${h.current}%` }}
          />
          <div className="absolute inset-y-0 w-px bg-copper/70" style={{ left: `${h.alarm}%` }} />
          <div className="absolute inset-y-0 w-px bg-danger" style={{ left: `${h.stop}%` }} />
        </div>
        <div className="mt-2 flex flex-wrap justify-between gap-2 text-[11px] text-ash">
          <span>
            Текущая <b className="text-danger">{h.current}%</b>
          </span>
          <span>
            Тревога {h.alarm}% · Стоп <b className="text-danger">{h.stop}%</b>
          </span>
          <span>
            Медиана флота <b className="text-ok">{h.median}%</b>
          </span>
        </div>
      </div>
    </Card>
  )
}

const feedTag: Record<string, { label: string; cls: string }> = {
  kill: { label: 'KILL', cls: 'text-danger' },
  bill: { label: 'БИЛЛИНГ', cls: 'text-copper' },
  alarm: { label: 'ALARM', cls: 'text-fog' },
  ok: { label: '●', cls: 'text-ok' },
}

function FeedCard() {
  return (
    <Card className="p-4">
      <CardHeader>
        <CardTitle>Лента тревог</CardTitle>
        <a className="cursor-pointer text-[12px] text-copper hover:underline">все →</a>
      </CardHeader>
      <div className="flex flex-col gap-2.5">
        {ov.feed.map((f, i) => (
          <div key={i} className="flex items-center gap-3 text-[12px]">
            <span className="w-10 shrink-0 tnum text-ash">{f.t}</span>
            <span className={`shrink-0 font-semibold ${feedTag[f.kind].cls}`}>{feedTag[f.kind].label}</span>
            <span className="truncate text-mist">{f.text}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}
