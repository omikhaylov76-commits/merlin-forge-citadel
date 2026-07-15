import { Link } from 'react-router-dom'
import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { clientsFixture as clients } from '@/lib/fixtures'

const money = (n: number) => '$' + n.toLocaleString('ru-RU')

// Экран Клиенты (по макету): плитки клиентов. Демо — живой источник = CRM-API ядра (/v1 clients).
export function Clients() {
  return (
    <div className="mx-auto max-w-[1216px]">
      <PageHead
        eyebrow="Клиенты"
        title="Клиенты"
        desc="12 клиентов · $248.6K под управлением"
        action={<Button variant="primary">+ Новый клиент</Button>}
      />
      <Toolbar>
        <Chip active>Все</Chip>
        <Chip>★ Избранные</Chip>
        <Chip>Ожидают биллинг</Chip>
      </Toolbar>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {clients.map((c) => (
          <Link key={c.name} to={`/clients/${encodeURIComponent(c.name)}`} className="block">
            <Card
              className={`h-full transition-colors hover:border-copper/30 ${c.fav ? 'border-gold/25' : ''}`}
            >
            <div className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold text-bone">
              {c.name}
              {c.fav && <span className="text-gold">★</span>}
            </div>
            <div className={`font-serif text-[24px] tnum ${c.gild ? 'gild' : 'text-bone'}`}>
              {money(c.capital)}
            </div>
            <div className="mt-0.5 text-[12px] text-fog">{c.sub}</div>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ash">
              {c.meta.map((m, i) => (
                <span key={i}>{m}</span>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-line pt-2 text-[11px]">
              <span className={c.toBill > 0 ? 'text-copper' : 'text-ash'}>
                К выставлению {money(c.toBill)}
              </span>
              <span className="text-ash">{c.note}</span>
            </div>
            </Card>
          </Link>
        ))}
        <button className="flex min-h-[150px] items-center justify-center rounded-card border border-dashed border-line text-[13px] text-fog transition-colors hover:text-mist">
          + Завести клиента
        </button>
      </div>
    </div>
  )
}
