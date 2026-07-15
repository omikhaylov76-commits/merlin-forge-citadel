import { PageHead } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { profilesFixture as profiles } from '@/lib/fixtures'

// Экран Профили (по макету + #40 п.4): библиотека рецептов. ТРИ доходностных героя (просадка /
// ср. доходность / недавняя), Calmar — справочным пиллом. Допущен=зелёный, demo=медный. Демо-данные.
export function Profiles() {
  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Кузница"
        title="Профили"
        desc="библиотека рецептов · 5 профилей"
        action={<Button variant="primary">Собрать профиль</Button>}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {profiles.map((p) => (
          <Card key={p.name} className={p.fav ? 'border-gold/25' : undefined}>
            <div className="mb-2 flex items-center justify-between">
              <b className="text-[14px] text-bone">{p.name}</b>
              <Badge tone={p.status === 'допущен' ? 'live' : 'alarm'}>{p.status}</Badge>
            </div>
            <div className={`text-[12px] ${p.status === 'допущен' ? 'text-ok' : 'text-fog'}`}>
              {p.track}
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2">
              <Metric label="Макс. просадка" value={p.dd} cls="text-danger" />
              <Metric label="Ср. доходность/год" value={p.avgReturn} cls="text-ok" />
              <Metric label="Недавняя · 12м" value={p.recentReturn} cls="text-ok" />
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-line pt-2.5 text-[11px] text-ash">
              <Badge tone="neutral">Calmar {p.calmar}</Badge>
              <span>
                деплоев: {p.deploys} ·{' '}
                <span className={p.oos.includes('✓') ? 'text-ok' : 'text-copper'}>{p.oos}</span>
              </span>
            </div>
          </Card>
        ))}
        <button className="flex min-h-[150px] items-center justify-center rounded-card border border-dashed border-line text-[13px] text-fog transition-colors hover:text-mist">
          + Собрать профиль
        </button>
      </div>
    </div>
  )
}

function Metric({ label, value, cls }: { label: string; value: string; cls: string }) {
  return (
    <div>
      <div className={`font-serif text-[22px] leading-none tnum ${cls}`}>{value}</div>
      <div className="mt-1 text-[10px] text-ash">{label}</div>
    </div>
  )
}
