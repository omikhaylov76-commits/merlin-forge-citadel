import { useMemo, useState, type ReactNode } from 'react'
import { PageHead, Chip } from '@/components/ui/page'
import { EmptyState } from '@/components/ui/states'
import { cn } from '@/lib/cn'
import { alertsFixture, type AlertSev } from '@/lib/fixtures'

// Иерархия severity (сверху — самое горящее). Две семьи: Торговые + Системные (спека #34).
const SEV_ORDER: AlertSev[] = ['KILL', 'ALARM', 'КЛЮЧ', 'HEARTBEAT', 'БИЛЛИНГ', 'СИСТЕМА']
const sevStyle: Record<AlertSev, string> = {
  KILL: 'border-danger/40 bg-danger/15 text-danger',
  ALARM: 'border-copper/40 bg-copper/15 text-copper',
  КЛЮЧ: 'border-line bg-floating text-steel',
  HEARTBEAT: 'border-line bg-floating text-mist',
  БИЛЛИНГ: 'border-gold/40 bg-gold/10 text-gold',
  СИСТЕМА: 'border-line bg-panel text-fog',
}

export function Alerts() {
  const [tab, setTab] = useState<'active' | 'resolved'>('active')
  const [family, setFamily] = useState<'Все' | 'Торговые' | 'Системные'>('Все')

  const list = useMemo(
    () =>
      alertsFixture
        .filter((a) => (tab === 'active' ? !a.resolved : a.resolved))
        .filter((a) => family === 'Все' || a.family === family)
        .slice()
        .sort((a, b) => SEV_ORDER.indexOf(a.sev) - SEV_ORDER.indexOf(b.sev)),
    [tab, family],
  )
  const activeCount = alertsFixture.filter((a) => !a.resolved).length

  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead eyebrow="Журналы" title="Тревоги" desc={`${activeCount} неразобранных`} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Tab active={tab === 'active'} onClick={() => setTab('active')}>
          Активные
        </Tab>
        <Tab active={tab === 'resolved'} onClick={() => setTab('resolved')}>
          Разобранные
        </Tab>
        <span className="mx-1 h-4 w-px bg-line" />
        {(['Все', 'Торговые', 'Системные'] as const).map((f) => (
          <Chip key={f} active={family === f} onClick={() => setFamily(f)}>
            {f}
          </Chip>
        ))}
      </div>

      {list.length === 0 ? (
        <div className="rounded-card border border-line bg-card">
          <EmptyState title="Пусто" hint="Нет тревог в этой вкладке." icon="✓" />
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {list.map((a, i) => (
            <div key={i} className="flex items-start gap-3 rounded-card border border-line bg-card p-4">
              <span
                className={cn(
                  'shrink-0 rounded-nav border px-2 py-1 text-[11px] font-semibold',
                  sevStyle[a.sev],
                )}
              >
                {a.sev}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-silver">{a.title}</div>
                <div className="mt-0.5 text-[12px] text-ash">{a.detail}</div>
              </div>
              <button className="shrink-0 text-[12px] text-copper hover:underline">{a.action}</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-nav px-3 py-1 text-[13px] transition-colors',
        active ? 'bg-floating text-bone' : 'text-fog hover:text-mist',
      )}
    >
      {children}
    </button>
  )
}
