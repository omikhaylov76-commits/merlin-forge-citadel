import { useState, type ReactNode } from 'react'
import { Card, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ConfirmModal } from '@/components/ui/modal'
import { clientDetailFixture as d } from '@/lib/fixtures'

const money = (n: number) => '$' + n.toLocaleString('ru-RU')

// Демо-портфель клиента (Клиент-11). Живой источник — CRM/telemetry ядра (только свои данные).
const portal = { capital: 61400, net: 5400, hwm: 56000, toBill: 812, bot: 'Скальпер', coins: ['ETH', 'SOL'] }

// Портал клиента (спека #34) — ОТДЕЛЬНАЯ read-only поверхность (здесь — превью для Оператора).
// Клиент видит ТОЛЬКО свой результат + монеты + имя бота; рецепт (крутилки/логика/пороги) СКРЫТ (IP-граница).
// Обе команды Пауза + Остановить — у клиента, каждая через «расписку» (модал последствий в числах).
export function Portal() {
  const [modal, setModal] = useState<null | 'pause' | 'stop'>(null)
  return (
    <div className="mx-auto max-w-[1216px]">
      <div className="mb-4 flex items-center gap-2 rounded-card border border-copper/25 bg-copper/5 px-4 py-2 text-[12px] text-copper">
        ◐ Портал клиента — превью. Клиент видит только свои результаты; рецепт (крутилки/логика/пороги) скрыт.
      </div>

      <div className="mb-4">
        <div className="text-[11px] uppercase tracking-widest text-ash">Ваш счёт</div>
        <div className="font-serif text-[28px] text-bone">Merlin Forge · портфель</div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Капитал" value={money(portal.capital)} gild />
        <Stat label="Заработано net" value={<span className="text-ok">+{money(portal.net)}</span>} />
        <Stat label="High-Water Mark" value={money(portal.hwm)} />
        <Stat label="Комиссия к уплате" value={money(portal.toBill)} gild accent />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Кривая капитала</CardTitle>
          <div className="flex h-40 items-center justify-center text-center text-[13px] text-ash">
            График появится после первых сделок
          </div>
        </Card>

        <Card>
          <CardTitle>Что в работе</CardTitle>
          <div className="mb-3 mt-2 flex items-center gap-2">
            <Badge tone="live">● в работе</Badge>
            <span className="text-[13px] text-silver">Бот «{portal.bot}»</span>
          </div>
          <div className="text-[12px] text-ash">Открытые позиции:</div>
          <table className="dt mt-1">
            <tbody>
              {d.positions.map((p) => (
                <tr key={p.pair}>
                  <td className="text-silver">{p.pair}</td>
                  <td className="num text-ok">+{money(p.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 text-[11px] text-ash">Монеты: {portal.coins.join(' · ')}</div>
        </Card>
      </div>

      <Card className="mt-4">
        <CardTitle>Документы</CardTitle>
        <div className="mt-2 flex items-center justify-between py-1 text-[13px]">
          <span className="text-silver">Расчёт HWM · июнь 2026</span>
          <button className="text-copper hover:underline">скачать</button>
        </div>
      </Card>

      <Card className="mt-4 border-copper/20">
        <CardTitle>Управление</CardTitle>
        <div className="mb-3 mt-1 text-[12px] text-ash">
          Две команды под вашим контролем — каждая под подтверждение.
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setModal('pause')}>‖ Пауза</Button>
          <Button variant="danger" onClick={() => setModal('stop')}>
            ✕ Остановить и закрыть
          </Button>
        </div>
      </Card>

      <ConfirmModal
        open={modal === 'pause'}
        tone="primary"
        confirmLabel="Поставить на паузу"
        title="Пауза бота"
        body="Бот перестанет ОТКРЫВАТЬ новые сделки; уже открытые позиции продолжат вестись. Ответственность за паузу — на вас: упущенную прибыль платформа не компенсирует."
        onConfirm={() => setModal(null)}
        onCancel={() => setModal(null)}
      />
      <ConfirmModal
        open={modal === 'stop'}
        tone="danger"
        confirmLabel="Остановить и закрыть всё"
        title="Остановить и закрыть"
        body={`Все открытые позиции (${d.positions.length}) будут ЗАКРЫТЫ по рынку, бот остановлен. Действие необратимо, результат фиксируется по текущей цене. Ответственность за остановку — на вас.`}
        onConfirm={() => setModal(null)}
        onCancel={() => setModal(null)}
      />
    </div>
  )
}

function Stat({
  label,
  value,
  gild,
  accent,
}: {
  label: string
  value: ReactNode
  gild?: boolean
  accent?: boolean
}) {
  return (
    <Card className={accent ? 'border-copper/30' : undefined}>
      <div className="mb-1 text-[11px] uppercase tracking-widest text-ash">{label}</div>
      <div className={`font-serif text-[24px] tnum ${gild ? 'gild' : 'text-bone'}`}>{value}</div>
    </Card>
  )
}
