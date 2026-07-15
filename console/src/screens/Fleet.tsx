import { PageHead, Toolbar, Chip, MiniDd } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { fleetFixture as rows } from '@/lib/fixtures'

const pnl = (n: number | null) =>
  n == null ? '—' : (n >= 0 ? '+' : '−') + '$' + Math.abs(n).toLocaleString('ru-RU')

const statusBadge = {
  live: { tone: 'live', label: '● в работе' },
  pause: { tone: 'pause', label: '‖ пауза' },
  alarm: { tone: 'alarm', label: '▲ тревога' },
  kill: { tone: 'kill', label: '✕ стоп' },
} as const

// Экран Флот (по макету): таблица ботов. Демо-данные — живой источник = список инстансов ядра.
export function Fleet() {
  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Флот"
        title="Флот"
        desc="19 ботов · 17 в работе · 2 на паузе"
        action={<Button variant="primary">Развернуть бота</Button>}
      />
      <Toolbar>
        <Chip active>Все</Chip>
        <Chip>В работе</Chip>
        <Chip>На паузе</Chip>
        <Chip>Тревога</Chip>
      </Toolbar>
      <div className="overflow-x-auto rounded-card border border-line bg-card">
        <table className="dt">
          <thead>
            <tr>
              <th>Бот</th>
              <th>Клиент</th>
              <th>Профиль</th>
              <th>Просадка</th>
              <th>HB</th>
              <th className="num">P&amp;L</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.bot}>
                <td className="font-semibold text-bone">{r.bot}</td>
                <td>{r.client}</td>
                <td className="text-fog">{r.profile}</td>
                <td>
                  <MiniDd value={r.dd} />
                </td>
                <td>
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${r.hb === 'ok' ? 'bg-ok' : 'bg-steel'}`}
                  />
                </td>
                <td className={`num ${r.pnl == null ? 'text-ash' : r.pnl >= 0 ? 'text-ok' : 'text-danger'}`}>
                  {pnl(r.pnl)}
                </td>
                <td>
                  <Badge tone={statusBadge[r.status].tone}>{statusBadge[r.status].label}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
