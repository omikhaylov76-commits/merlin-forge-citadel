import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAsync } from '@/lib/useAsync'
import { getClients } from '@/lib/api'

const plural = (n: number) => (n % 10 === 1 && n % 100 !== 11 ? 'клиент' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 'клиента' : 'клиентов')

// Экран Клиенты: ЖИВОЙ список из CRM-API ядра (/v1/clients) вместо фикстуры.
// v1-плитка минимальна (имя + активность): капитал/комиссия на договорах — по мере вывода экранов на живьё.
export function Clients() {
  const clients = useAsync(getClients, [])
  const list = clients.data ?? []
  const desc = clients.loading
    ? 'загрузка…'
    : clients.error
      ? '— · нет связи с ядром'
      : `${list.length} ${plural(list.length)} · живые из ядра`

  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Клиенты"
        title="Клиенты"
        desc={desc}
        action={<Button variant="primary">+ Новый клиент</Button>}
      />
      <Toolbar>
        <Chip active>Все</Chip>
        <Chip>★ Избранные</Chip>
        <Chip>Ожидают биллинг</Chip>
      </Toolbar>

      {clients.error ? (
        <Card className="text-[13px] text-danger">Нет связи с ядром: {clients.error.message}</Card>
      ) : clients.loading ? (
        <Card className="animate-pulse text-[13px] text-ash">Загрузка клиентов из ядра…</Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((c) => (
            <Card key={c.id} className="h-full">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-[14px] font-semibold text-bone">{c.name}</span>
                <span className={`text-[11px] ${c.is_active ? 'text-ok' : 'text-ash'}`}>
                  {c.is_active ? '● активен' : '○ неактивен'}
                </span>
              </div>
              <div className="text-[12px] text-fog">клиент · живой из CRM ядра</div>
              <div className="mt-3 flex items-center justify-between border-t border-line pt-2 text-[11px] text-ash">
                <span className="tnum">{c.id.slice(0, 8)}…</span>
                <span>ядро · живое</span>
              </div>
            </Card>
          ))}
          <button className="flex min-h-[120px] items-center justify-center rounded-card border border-dashed border-line text-[13px] text-fog transition-colors hover:text-mist">
            + Завести клиента
          </button>
        </div>
      )}
    </div>
  )
}
