import { useState } from 'react'
import { PageHead } from '@/components/ui/page'
import { Card } from '@/components/ui/card'
import { EmptyState, ErrorState, Loading } from '@/components/ui/states'
import { useAsync } from '@/lib/useAsync'
import { getBasket, removeBasketItem, type BasketItem } from '@/lib/api'

// Экран «Набор» (НАБОР-1): корзина отмеченных Оператором сетапов — витрина + хранение, НИЧЕГО не
// торгует. Звёздочка на сетапе (Разведка) складывает сюда монету с контекстом; здесь — список с
// возможностью убрать лишнее. Передача боту (НАБОР-2) — отдельным шагом, строго со спекой Куратора.

const ts = (s?: string | null) => (s ? s.slice(0, 19).replace('T', ' ') : '—')
const ctxNum = (c: Record<string, unknown>, k: string) =>
  typeof c[k] === 'number' ? (c[k] as number) : undefined
const ctxStr = (c: Record<string, unknown>, k: string) =>
  typeof c[k] === 'string' ? (c[k] as string) : undefined

export function Basket() {
  const list = useAsync(getBasket, [])
  const [busy, setBusy] = useState<string | null>(null)

  async function remove(id: string) {
    setBusy(id)
    try {
      await removeBasketItem(id)
      list.reload()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <PageHead
        eyebrow="Кузница"
        title="Набор"
        desc="Отмеченные сетапы — витрина и хранение. Ничего не торгует; передача боту — отдельным шагом."
        action={
          list.data ? (
            <span className="rounded-pill border border-line px-3 py-1 text-[12px] text-fog tnum">
              {list.data.length} в наборе
            </span>
          ) : undefined
        }
      />

      {list.loading && <Loading />}
      {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
      {list.data && list.data.length === 0 && (
        <EmptyState
          icon="★"
          title="Набор пуст"
          hint="Откройте сетап в Разведке и нажмите звёздочку — монета сложится сюда с контекстом сетапа."
        />
      )}
      {list.data && list.data.length > 0 && (
        <div className="space-y-2">
          {list.data.map((it) => (
            <Row key={it.id} it={it} onRemove={() => remove(it.id)} busy={busy === it.id} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ it, onRemove, busy }: { it: BasketItem; onRemove: () => void; busy: boolean }) {
  const score = ctxNum(it.context, 'score')
  const stage = ctxStr(it.context, 'stage')
  const impulse = ctxNum(it.context, 'impulse') ?? ctxNum(it.context, 'impulse_ratio')
  return (
    <Card className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 py-3.5">
      <div className="min-w-[130px]">
        <div className="font-serif text-[19px] leading-none text-bone">{it.symbol}</div>
        <div className="mt-1 text-[11px] text-ash">добавлено {ts(it.created_at)}</div>
      </div>
      <span className="rounded-pill border border-line px-2 py-0.5 text-[11px] text-fog">{it.tf}</span>
      <span className="rounded-pill border border-line px-2 py-0.5 text-[11px] text-fog">
        {it.source === 'scout' ? 'разведка' : 'скринер'}
      </span>
      {stage && <span className="text-[12px] text-mist">{stage}</span>}
      {score != null && (
        <span className="text-[12px] text-fog tnum">
          скор <span className="text-mist">{Math.round(score)}</span>
        </span>
      )}
      {impulse != null && (
        <span className="text-[12px] text-fog tnum">импульс ×{impulse.toFixed(2)}</span>
      )}
      {it.note && <span className="text-[12px] text-fog italic">«{it.note}»</span>}
      <button
        onClick={onRemove}
        disabled={busy}
        className="ml-auto rounded-pill border border-line px-3 py-1 text-[12px] text-fog transition-colors hover:border-danger/40 hover:text-danger disabled:opacity-50"
      >
        {busy ? '…' : '✕ убрать'}
      </button>
    </Card>
  )
}
