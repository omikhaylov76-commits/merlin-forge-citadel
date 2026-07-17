import { type ScoutSnapshot } from '@/lib/api'
import { boardColumn, levelOf, pctToEntry } from '@/lib/scout'
import { Sparkline } from './Sparkline'

const fmt = (n?: number) => (n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 6 }))

// Карточка кандидата (по макету): пара · скор · возраст · входы+стоп · %-до-входа (снимок) · спарклайн.
// Звёздочка «в Наборе» — прямо на карточке (макет razvedka-page-layout .star; фидбэк Оператора:
// видно выбранных без захода в деталь). span, не button — карточка сама <button> (HTML-валидность).
export function ScoutCard({
  snap,
  onOpen,
  starred,
  starBusy,
  onStar,
}: {
  snap: ScoutSnapshot
  onOpen: () => void
  starred?: boolean
  starBusy?: boolean
  onStar?: () => void
}) {
  const col = boardColumn(snap)
  const ready = col === 'ready'
  const committed = col === 'committed'
  const e382 = levelOf(snap, 'entry_0382')
  const e05 = levelOf(snap, 'entry_05')
  const e0618 = levelOf(snap, 'entry_0618')
  const stop = levelOf(snap, 'stop')
  const pct = pctToEntry(snap)

  return (
    <button
      onClick={onOpen}
      className={`w-full rounded-card border bg-panel px-3 py-2.5 text-left transition-colors ${
        ready ? 'border-gold/25 hover:border-gold/40' : 'border-line hover:border-copper/30'
      } ${committed ? 'opacity-70' : ''}`}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <b className="text-[13px] text-bone">{snap.symbol}</b>
          <span className="rounded-pill border border-copper/30 px-1.5 text-[10px] text-copper">
            {snap.tf}
          </span>
          <span className="rounded-pill border border-line px-1.5 text-[10px] text-ash">long</span>
          {snap.config_mismatch?.flag && (
            <span className="text-danger" title="конфиг разведки разошёлся с движком">
              ⚠
            </span>
          )}
        </span>
        <span className="flex items-center gap-1.5">
          {onStar && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation()
                if (!starBusy) onStar()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.stopPropagation()
                  e.preventDefault()
                  if (!starBusy) onStar()
                }
              }}
              title={starred ? 'Убрать из Набора' : 'В Набор'}
              className={`text-[14px] leading-none transition-colors ${
                starBusy ? 'opacity-50' : ''
              } ${starred ? 'text-gold' : 'text-[#3a3d46] hover:text-fog'}`}
            >
              {starred ? '★' : '☆'}
            </span>
          )}
          <span className={committed ? 'text-[12px] text-ash' : 'gild font-serif text-[15px] tnum'}>
            {committed ? 'взят' : Math.round(snap.score)}
          </span>
        </span>
      </div>

      {snap.state === 'forming' ? (
        <div className="text-[11px] text-ash">формируется · греется</div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <Sparkline klines={snap.klines} entryHi={e382} entryLo={e0618} />
            <div className="text-right text-[11px] tnum">
              {pct != null && (
                <div
                  className={pct >= 0 ? 'text-fog' : 'text-ok'}
                  title={`на закрытие ${snap.data_upto}`}
                >
                  {pct >= 0 ? '+' : ''}
                  {pct.toFixed(2)}% до входа
                </div>
              )}
              <div className="text-ash">возраст {snap.bars_since_anchor ?? '—'} бар.</div>
            </div>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-ash tnum">
            <span>вх 0.382 {fmt(e382)}</span>
            <span>0.5 {fmt(e05)}</span>
            <span>0.618 {fmt(e0618)}</span>
            <span className="text-danger/80">стоп {fmt(stop)}</span>
          </div>
        </>
      )}
    </button>
  )
}
