import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Button } from '@/components/ui/button'
import { scoutFixture as cols } from '@/lib/fixtures'

// Экран Разведка (по макету): kanban скаута (Forming/Tracking/Ready/Committed). Демо — живой
// источник = scout-сервис. Ready-колонка золочёная. Committed-кандидаты приглушены (уже взяты ботом).
export function Scout() {
  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Кузница"
        title="Разведка"
        desc="сканер сетапов · обновлено 12с назад · ТФ 4h"
        action={<Button>Сканировать сейчас</Button>}
      />
      <Toolbar>
        <Chip active>Топ-100</Chip>
        <Chip>Оборот ≥ $5M</Chip>
        <Chip>Скор ≥ 35</Chip>
        <Chip>Long</Chip>
      </Toolbar>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cols.map((col) => (
          <div
            key={col.column}
            className={`rounded-card border bg-card p-3 ${col.ready ? 'border-gold/25' : 'border-line'}`}
          >
            <div className="mb-3 flex items-center justify-between px-1">
              <span className="text-[12px] font-semibold uppercase tracking-wide text-mist">
                {col.column}
              </span>
              <span className="text-[11px] text-ash">{col.count}</span>
            </div>
            <div className="flex flex-col gap-2">
              {col.cands.map((c) => (
                <div
                  key={c.pair}
                  className={`rounded-card border bg-panel px-3 py-2.5 ${
                    col.ready ? 'border-gold/20' : 'border-line'
                  } ${c.committed ? 'opacity-70' : ''}`}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <b className="text-[13px] text-bone">{c.pair}</b>
                    <span
                      className={c.committed ? 'text-[12px] text-ash' : 'gild font-serif text-[15px] tnum'}
                    >
                      {c.score}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2 text-[11px] text-ash">
                    <span>{c.m1}</span>
                    <span>{c.m2}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
