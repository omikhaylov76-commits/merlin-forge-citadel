import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Badge } from '@/components/ui/badge'
import { dealsFixture as rows } from '@/lib/fixtures'

const pnl = (n: number) => (n >= 0 ? '+' : '−') + '$' + Math.abs(n).toLocaleString('ru-RU')

// Экран Сделки (по макету): журнал ордеров флота. Демо — живой источник = trades ядра.
export function Deals() {
  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead eyebrow="Флот" title="Сделки" desc="журнал ордеров по всему флоту" />
      <Toolbar>
        <Chip active>Сегодня</Chip>
        <Chip>7 дней</Chip>
        <Chip>Месяц</Chip>
        <Chip>Экспорт CSV</Chip>
      </Toolbar>
      <div className="overflow-x-auto rounded-card border border-line bg-card">
        <table className="dt">
          <thead>
            <tr>
              <th>Время</th>
              <th>Бот</th>
              <th>Пара</th>
              <th>Сторона</th>
              <th>Нога</th>
              <th className="num">Цена</th>
              <th className="num">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="tnum text-fog">{r.t}</td>
                <td className="font-semibold text-bone">{r.bot}</td>
                <td>{r.pair}</td>
                <td>
                  <Badge tone="live">{r.side}</Badge>
                </td>
                <td className="text-fog">{r.leg}</td>
                <td className="num">{r.price}</td>
                <td className={`num ${r.pnl >= 0 ? 'text-ok' : 'text-danger'}`}>{pnl(r.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
