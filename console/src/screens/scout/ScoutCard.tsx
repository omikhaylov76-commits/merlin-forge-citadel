import { type ScoutSnapshot } from '@/lib/api'
import { entryOf, pctToEntry, skipReason, stopOf, verdictColumn } from '@/lib/scout'
import { Sparkline } from './Sparkline'

const fmt = (n?: number) => (n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 6 }))

// Карточка кандидата единой Разведки: строка радара (стадия+скор) · спарклайн с зоной входа ·
// %-до-входа/возраст · СТРОКА ВЕРДИКТА движка (факты engine; для skip — причина+судьба) · сетка
// (входы/стоп — приоритет правды движка) · ★ Набор. Дисклеймер подписи Куратора — в title вердикта
// и сноской доски: это СНИМОК скаута, не живой тик.
const STAGE_RU: Record<string, string> = {
  forming: 'формируется',
  tracking: 'отслеж.',
  ready: 'готов',
}

const VERDICT_BADGE: Record<string, { text: string; cls: string }> = {
  in_work: { text: '● в работе', cls: 'border-ok/40 bg-ok/10 text-ok' },
  auto: { text: '◆ движок ставит', cls: 'border-gold/40 bg-gold/10 text-gold' },
  button: { text: '⚑ нужна кнопка', cls: 'border-copper/45 bg-copper/10 text-copper' },
}

export function ScoutCard({
  snap,
  onOpen,
  starred,
  starBusy,
  onStar,
  warmState,
  onWarm,
}: {
  snap: ScoutSnapshot
  onOpen: () => void
  starred?: boolean
  starBusy?: boolean
  onStar?: () => void
  // Кнопка «Поставить» (F-warm-button, ADR-0022 — переиспользуем команду warm_apply) — только
  // колонка «нужна кнопка». idle→busy→sent (⏳ ждёт 15m-тик); движок сам валидирует.
  warmState?: 'idle' | 'busy' | 'sent'
  onWarm?: () => void
}) {
  const col = verdictColumn(snap)
  const reason = skipReason(snap)
  const badge = VERDICT_BADGE[col]
  const e382 = entryOf(snap, '0.382')
  const e05 = entryOf(snap, '0.5')
  const e0618 = entryOf(snap, '0.618')
  const stop = stopOf(snap)
  const pct = pctToEntry(snap)
  const engineGrid = Boolean(snap.engine?.entries) // сетка от движка, не оценка скаута

  return (
    <button
      onClick={onOpen}
      className={`w-full rounded-card border bg-panel px-3 py-2.5 text-left transition-colors ${
        col === 'auto'
          ? 'border-gold/25 hover:border-gold/40'
          : col === 'button'
            ? 'border-copper/30 hover:border-copper/50'
            : 'border-line hover:border-copper/30'
      } ${col === 'in_work' ? 'opacity-80' : ''}`}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <b className="text-[13px] text-bone">{snap.symbol}</b>
          <span className="rounded-pill border border-line px-1.5 text-[10px] text-ash">
            {STAGE_RU[snap.state] ?? snap.state}
          </span>
          {snap.engine?.side && (
            <span className="rounded-pill border border-line px-1.5 text-[10px] text-ash">
              {snap.engine.side}
            </span>
          )}
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
          <span className="gild font-serif text-[15px] tnum">{Math.round(snap.score)}</span>
        </span>
      </div>

      {/* строка ВЕРДИКТА движка — сердце единой Разведки (снимок скаута, не живой тик) */}
      <div className="mb-1.5 flex items-center gap-1.5">
        {badge ? (
          <span
            className={`rounded-pill border px-2 py-0.5 text-[10px] ${badge.cls}`}
            title="правда движка по снимку скаута (не живой тик): warm-реплей той же функции, что ставит ордера"
          >
            {badge.text}
          </span>
        ) : (
          <span
            className="rounded-pill border border-line px-2 py-0.5 text-[10px] text-steel"
            title={reason ? `${reason.fate} · снимок скаута, не живой тик` : undefined}
          >
            ✕ {reason?.label ?? 'не берёт'}
          </span>
        )}
        {col === 'button' && onWarm && (
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              if (warmState === 'idle') onWarm()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation()
                e.preventDefault()
                if (warmState === 'idle') onWarm()
              }
            }}
            title="Поставить сетап в ордера (warm_apply): движок проверит годность на ближайшем 15m-тике"
            className={`rounded-pill border px-2 py-0.5 text-[10px] transition-colors ${
              warmState === 'sent'
                ? 'border-ok/40 bg-ok/10 text-ok'
                : warmState === 'busy'
                  ? 'border-line text-ash'
                  : 'border-copper/45 bg-copper/10 text-copper hover:border-copper/70'
            }`}
          >
            {warmState === 'sent' ? '⏳ ждёт тик' : warmState === 'busy' ? '…' : 'Поставить'}
          </span>
        )}
      </div>

      {snap.state === 'forming' && !snap.engine?.entries ? (
        <div className="text-[11px] text-ash">формируется · уровней ещё нет</div>
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <Sparkline klines={snap.klines} entryHi={e382} entryLo={e0618} />
            <div className="text-right text-[11px] tnum">
              {pct != null && (
                <div
                  className={pct >= 0 ? 'text-fog' : 'text-ok'}
                  title={`на закрытие ${snap.data_upto} — снимок, не живой тик`}
                >
                  {pct >= 0 ? '+' : ''}
                  {pct.toFixed(2)}% до входа
                </div>
              )}
              <div className="text-ash">
                возраст {snap.engine?.age_bars ?? snap.bars_since_anchor ?? '—'} бар.
              </div>
            </div>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-ash tnum">
            <span title={engineGrid ? 'сетка движка (warm-реплей)' : 'оценка скаута'}>
              вх 0.382 {fmt(e382)}
            </span>
            <span>0.5 {fmt(e05)}</span>
            <span>0.618 {fmt(e0618)}</span>
            <span className="text-danger/80">стоп {fmt(stop)}</span>
            {engineGrid && (
              <span className="text-copper/80" title="уровни — реальная сетка постановки движка">
                сетка движка
              </span>
            )}
          </div>
        </>
      )}
    </button>
  )
}
