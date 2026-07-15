import { type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Card, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { MiniDd } from '@/components/ui/page'
import { clientsFixture, clientDetailFixture as d } from '@/lib/fixtures'

const money = (n: number) => (n < 0 ? '−' : '') + '$' + Math.abs(n).toLocaleString('ru-RU')
const moneyK = (n: number) =>
  (n < 0 ? '−' : '+') + '$' + (Math.abs(n) / 1000).toFixed(1).replace('.', ',') + 'K'

// Карточка клиента (по макету s-client): KPI + боты/позиции + периоды-биллинг/движение/договор.
// Демо-деталь (представительная); живые данные — CRM/telemetry ядра (TODO Ф4-backend).
export function ClientCard() {
  const { id } = useParams()
  const c = clientsFixture.find((x) => x.name === id) ?? clientsFixture[0]
  return (
    <div className="mx-auto max-w-[1880px]">
      <Link to="/clients" className="text-[12px] text-copper hover:underline">
        ← Клиенты
      </Link>
      <div className="mb-4 mt-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-widest text-ash">Клиент</div>
          <div className="flex items-center gap-2 font-serif text-[28px] text-bone">
            {c.name}
            {c.fav && <span className="text-gold">★</span>}
          </div>
          <div className="mt-0.5 text-[13px] text-fog">
            {c.exchange} · договор {c.contractStatus} · {c.note}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="default">Портал-превью</Button>
          <Button variant="primary">Закрыть период → счёт</Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Капитал" value={money(c.capital)} gild />
        <Stat
          label="Заработано net"
          value={<span className={c.net >= 0 ? 'text-ok' : 'text-danger'}>{moneyK(c.net)}</span>}
        />
        <Stat label="HWM" value={money(c.hwm)} />
        <Stat
          label="К выставлению"
          value={money(c.toBill)}
          gild
          accent
          sub={c.toBill > 0 ? '7 дней до закрытия' : 'под HWM'}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Боты клиента</CardTitle>
          <table className="dt mt-2">
            <tbody>
              {d.bots.map((b) => (
                <tr key={b.bot}>
                  <td className="font-semibold text-bone">
                    {b.bot} <span className="font-normal text-fog">· {b.profile}</span>
                  </td>
                  <td>
                    <MiniDd value={b.dd} />
                  </td>
                  <td className="num text-ok">+{money(b.pnl)}</td>
                  <td>
                    <Badge tone="live">● в работе</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <CardTitle className="mt-5">Все открытые позиции</CardTitle>
          <table className="dt mt-2">
            <thead>
              <tr>
                <th>Пара</th>
                <th>Нога</th>
                <th className="num">Вход</th>
                <th className="num">P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {d.positions.map((p) => (
                <tr key={p.pair}>
                  <td>{p.pair}</td>
                  <td className="text-fog">{p.leg}</td>
                  <td className="num">{p.entry}</td>
                  <td className="num text-ok">+{money(p.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardTitle>Биллинг · периоды</CardTitle>
          <div className="mt-2 flex flex-col divide-y divide-line">
            {d.periods.map((p) => (
              <div key={p.month} className="flex items-center justify-between py-2.5">
                <div>
                  <div className="text-[13px] text-silver">{p.month}</div>
                  <div className="text-[11px] text-ash">{p.note}</div>
                </div>
                <span className={`text-[13px] tnum ${p.open ? 'text-copper' : 'text-fog'}`}>
                  {money(p.amount)}
                </span>
              </div>
            ))}
          </div>

          <CardTitle className="mt-5">Движение средств</CardTitle>
          <div className="mt-2 flex flex-col divide-y divide-line">
            {d.cashflows.map((f, i) => (
              <div key={i} className="flex items-center justify-between py-2.5">
                <div>
                  <div className="text-[13px] text-silver">{f.label}</div>
                  <div className="text-[11px] text-ash">{f.note}</div>
                </div>
                <span className="text-ok">{f.sign}</span>
              </div>
            ))}
          </div>

          <CardTitle className="mt-5">Договор</CardTitle>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge tone="gold">HWM {d.contract.hwm}</Badge>
            <Badge>период {d.contract.period}</Badge>
            <Badge>{d.contract.currency}</Badge>
            <Badge>мин {d.contract.min}</Badge>
            <Badge tone="live">{c.contractStatus}</Badge>
          </div>
        </Card>
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  sub,
  gild,
  accent,
}: {
  label: string
  value: ReactNode
  sub?: string
  gild?: boolean
  accent?: boolean
}) {
  return (
    <Card className={accent ? 'border-copper/30' : undefined}>
      <div className="mb-1 text-[11px] uppercase tracking-widest text-ash">{label}</div>
      <div className={`font-serif text-[24px] tnum ${gild ? 'gild' : 'text-bone'}`}>{value}</div>
      {sub && <div className="mt-1 text-[12px] text-fog">{sub}</div>}
    </Card>
  )
}
