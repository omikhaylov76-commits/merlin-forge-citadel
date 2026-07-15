import { PageHead } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { profilesFixture as profiles } from '@/lib/fixtures'

// Экран Профили (по макету): библиотека рецептов. Допущен = зелёный (живой трек+OOS), demo = медный.
export function Profiles() {
  return (
    <div className="mx-auto max-w-[1216px]">
      <PageHead
        eyebrow="Кузница"
        title="Профили"
        desc="библиотека рецептов · 5 профилей"
        action={<Button variant="primary">Собрать профиль</Button>}
      />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {profiles.map((p) => (
          <Card key={p.name} className={p.fav ? 'border-gold/25' : undefined}>
            <div className="mb-3 flex items-center justify-between">
              <b className="text-[14px] text-bone">{p.name}</b>
              <Badge tone={p.status === 'допущен' ? 'live' : 'alarm'}>{p.status}</Badge>
            </div>
            <div className={`text-[12px] ${p.status === 'допущен' ? 'text-ok' : 'text-fog'}`}>
              {p.track}
            </div>
            <div className="mt-3 flex gap-6">
              <div>
                <div className="font-serif text-[22px] tnum text-bone">{p.calmar}</div>
                <div className="text-[11px] text-ash">Calmar</div>
              </div>
              <div>
                <div className="font-serif text-[22px] tnum text-bone">{p.dd}</div>
                <div className="text-[11px] text-ash">макс. просадка</div>
              </div>
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-line pt-2 text-[11px] text-ash">
              <span>деплоев: {p.deploys}</span>
              <span className={p.oos.includes('✓') ? 'text-ok' : 'text-copper'}>{p.oos}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
