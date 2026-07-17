import { useState } from 'react'
import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useAsync } from '@/lib/useAsync'
import { getFleetInstances, type FleetInstance } from '@/lib/api'
import { BotCard } from './fleet/BotCard'

const money = (n: string | null) => (n == null ? '—' : '$' + Number(n).toLocaleString('ru-RU'))

// статус инстанса ядра → бейдж консоли (running=в работе, paused=пауза, stopped/failed=стоп, прочее=переход)
function badge(status: string): { tone: 'live' | 'pause' | 'alarm' | 'kill'; label: string } {
  if (status === 'running') return { tone: 'live', label: '● в работе' }
  if (status === 'paused') return { tone: 'pause', label: '‖ пауза' }
  if (['stopped', 'failed', 'failed_deploy', 'stopping_failed'].includes(status))
    return { tone: 'kill', label: '✕ ' + status }
  return { tone: 'alarm', label: '… ' + status } // pending/deploying/starting/stopping
}

// Экран Флот: ЖИВАЯ таблица инстансов ядра (/v1/fleet/instances). Бот = инстанс.
// Профиль/просадка/P&L per-instance пока не выведены ядром — показываем клиент/equity/health/статус.
export function Fleet() {
  const fleet = useAsync(getFleetInstances, [])
  const rows = fleet.data ?? []
  const [card, setCard] = useState<FleetInstance | null>(null)
  const desc = fleet.loading
    ? 'загрузка…'
    : fleet.error
      ? '— · нет связи с ядром'
      : `${rows.length} ${rows.length === 1 ? 'бот' : 'ботов'} · живые из ядра`

  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Флот"
        title="Флот"
        desc={desc}
        action={<Button variant="primary">Развернуть бота</Button>}
      />
      <Toolbar>
        <Chip active>Все</Chip>
        <Chip>В работе</Chip>
        <Chip>На паузе</Chip>
        <Chip>Тревога</Chip>
      </Toolbar>

      {fleet.error ? (
        <Card className="text-[13px] text-danger">Нет связи с ядром: {fleet.error.message}</Card>
      ) : fleet.loading ? (
        <Card className="animate-pulse text-[13px] text-ash">Загрузка флота из ядра…</Card>
      ) : (
        <div className="overflow-x-auto rounded-card border border-line bg-card">
          <table className="dt">
            <thead>
              <tr>
                <th>Бот</th>
                <th>Клиент</th>
                <th className="num">Equity</th>
                <th>HB</th>
                <th>Статус</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const b = badge(r.status)
                return (
                  <tr
                    key={r.id}
                    onClick={() => setCard(r)}
                    className="cursor-pointer transition-colors hover:bg-panel/60"
                  >
                    <td className="font-semibold text-bone tnum">{r.id.slice(0, 8)}…</td>
                    <td>{r.client}</td>
                    <td className="num tnum">{money(r.equity)}</td>
                    <td>
                      <span
                        className={`inline-block h-2 w-2 rounded-full ${r.health === 'ok' ? 'bg-ok' : 'bg-steel'}`}
                      />
                    </td>
                    <td>
                      <Badge tone={b.tone}>{b.label}</Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {card && <BotCard inst={card} onClose={() => setCard(null)} />}
    </div>
  )
}
