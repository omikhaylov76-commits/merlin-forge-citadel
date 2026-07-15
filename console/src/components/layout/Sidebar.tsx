import { NavLink, useNavigate } from 'react-router-dom'
import { NAV } from '@/lib/nav'
import { logout, getFleetOverview } from '@/lib/api'
import { useAsync } from '@/lib/useAsync'
import { cn } from '@/lib/cn'

// Сайдбар консоли: бренд · ЖИВАЯ сводка AUM (/fleet/overview) · навигация · футер (оператор+выход).
export function Sidebar() {
  const nav = useNavigate()
  const fleet = useAsync(getFleetOverview, [])
  const money = (n: string) => '$' + Number(n).toLocaleString('ru-RU')
  const onLogout = () => {
    logout()
    nav('/login', { replace: true })
  }
  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r border-line bg-void">
      <div className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-card border border-copper/40 text-lg text-copper">
          ◈
        </div>
        <div className="leading-tight">
          <div className="font-serif text-[16px] text-bone">Citadel</div>
          <div className="text-[11px] text-ash">Merlin Forge</div>
        </div>
      </div>

      <div className="mx-4 mb-3 rounded-card border border-line bg-card px-4 py-3">
        <div className="text-[10px] uppercase tracking-widest text-ash">Активы под управлением</div>
        <div className="gild font-serif text-[22px] tnum">
          {fleet.loading ? '…' : fleet.error || !fleet.data ? '—' : money(fleet.data.aum)}
        </div>
        <div className="flex items-center justify-between text-[11px] text-fog">
          <span>{fleet.data ? `${fleet.data.bots.running} / ${fleet.data.bots.total} ботов` : '— ботов'}</span>
          <span className="text-ash">{fleet.data ? `${fleet.data.clients} кл.` : ''}</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {NAV.map((group, gi) => (
          <div key={gi} className="mb-0.5">
            {group.title && (
              <div className="px-2 pb-1 pt-3 text-[10px] uppercase tracking-widest text-steel">
                {group.title}
              </div>
            )}
            {group.items.map((it) => (
              <NavLink
                key={it.path}
                to={it.path}
                end={it.path === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-2.5 rounded-nav px-2.5 py-2 text-[13px] transition-colors',
                    isActive
                      ? 'bg-floating text-bone'
                      : 'text-fog hover:bg-floating/60 hover:text-mist',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={cn(
                        'w-4 text-center text-[13px]',
                        isActive ? 'text-copper' : 'text-steel',
                      )}
                    >
                      {it.icon}
                    </span>
                    <span className="flex-1">{it.label}</span>
                    {it.badge != null && (
                      <span
                        className={cn(
                          'rounded-pill px-1.5 text-[10px]',
                          it.hot ? 'bg-danger/20 text-danger' : 'bg-floating text-ash',
                        )}
                      >
                        {it.badge}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="border-t border-line px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-[11px] text-fog">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" /> Кавалл · система в норме
        </div>
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-pill bg-floating text-[12px] text-mist">
            М
          </div>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="text-[12px] text-silver">Оператор</div>
            <div className="text-[10px] text-ash">merlin@citadel</div>
          </div>
          <button
            onClick={onLogout}
            title="Выйти"
            aria-label="Выйти"
            className="shrink-0 rounded-pill px-2 py-1 text-[13px] text-ash transition-colors hover:text-danger"
          >
            ⏻
          </button>
        </div>
      </div>
    </aside>
  )
}
