import { useEffect, useState } from 'react'
import {
  getEngineState,
  getInstanceScout,
  scanNow,
  warmApply,
  type EngineStack,
  type EngineStateResp,
  type FleetInstance,
  type ScoutSnapshot,
} from '@/lib/api'
import { skipReason } from '@/lib/scout'
import { ScoutDetail } from '../scout/ScoutDetail'

const WARM_TICK_MS = 16 * 60_000 // окно до исполнения warm на ближайшем 15m-тике

// Карточка бота (S7): клик по строке Флота → факт-слой движка. Дизайн «midnight vault + gilded lines»:
// ФИКСИРОВАННАЯ шапка-герой (статус/equity/пик/просадка/флаги) + скроллящееся тело (плитки + секции-
// гармошки). .dt-таблицы, лог событий, смысловой цвет PnL. Автообновление ~5с (engine_state readout).

const num = (n?: number) => (n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 6 }))
const money = (n?: number) =>
  n == null ? '—' : '$' + n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
const signed = (n?: number) =>
  n == null ? '—' : (n > 0 ? '+' : '') + n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
const pnlCls = (n?: number) => (n && n > 0 ? 'text-ok' : n && n < 0 ? 'text-danger' : 'text-mist')
const ts = (s?: string) => (s ? s.slice(0, 19).replace('T', ' ') : '—')

const STATE: Record<string, { label: string; cls: string }> = {
  NORMAL: { label: '● в работе', cls: 'border-ok/40 bg-ok/10 text-ok' },
  RUNNING: { label: '● в работе', cls: 'border-ok/40 bg-ok/10 text-ok' },
  WARMING: { label: '◐ прогрев', cls: 'border-gold/40 bg-gold/10 text-gold' },
  NO_DATA: { label: '○ нет биржевых данных', cls: 'border-line text-steel' },
  STOPPING: { label: '■ остановка', cls: 'border-danger/40 bg-danger/10 text-danger' },
  STOPPED: { label: '■ остановлен', cls: 'border-danger/40 bg-danger/10 text-danger' },
  PAUSED: { label: '‖ пауза', cls: 'border-copper/40 bg-copper/10 text-copper' },
}
const chipOf = (s?: string) =>
  STATE[(s ?? '').toUpperCase()] ?? { label: s || '—', cls: 'border-line text-fog' }

export function BotCard({ inst, onClose }: { inst: FleetInstance; onClose: () => void }) {
  const [resp, setResp] = useState<EngineStateResp | null>(null)
  const [err, setErr] = useState(false)
  const [detail, setDetail] = useState<ScoutSnapshot | null>(null) // клик по монете стека → график Разведки
  const [pickErr, setPickErr] = useState<string | null>(null)
  // #3: скан переживает уход/возврат (localStorage, общий с Разведкой) — не «висит с нуля».
  const [scanState, setScanState] = useState<'idle' | 'busy' | 'sent' | 'err'>(() => {
    const v = Number(localStorage.getItem(`mfc.scanAt.${inst.id}`) || 0)
    return v && Date.now() - v < 120_000 ? 'sent' : 'idle'
  })
  // F-warm-button (ADR-0022): мультивыбор сетапов → ОДНА команда warm_apply (движок за один тик
  // разберёт пачку, поставит только годные PENDING; невалидные молча skip). Список — уже в контракте.
  const [warmSel, setWarmSel] = useState<Set<string>>(new Set())
  const [warmBatch, setWarmBatch] = useState<'idle' | 'busy' | 'sent' | 'err'>('idle')
  // symbol → момент отправки warm (мс). Держим, чтобы показать СУДЬБУ после ⏳: поставлено (в
  // ордерах) / не взято + причина (из вердикта движка scout-снимка). Не тихий Set (жалоба Оператора).
  const [warmSentAt, setWarmSentAt] = useState<Record<string, number>>({})
  // scout-снимки этого бота (engine-поле = вердикт движка per-coin) — для причины «не взято».
  const [scoutSnaps, setScoutSnaps] = useState<ScoutSnapshot[]>([])

  // Кнопка «Сканировать сейчас» прямо на карточке (просьба Оператора): та же команда scan_now,
  // что на Разведке — скаут пересканирует (~1-2 мин), свечи/сетапы/графики обновятся сами.
  const doScan = async () => {
    setScanState('busy')
    try {
      await scanNow(inst.id)
      localStorage.setItem(`mfc.scanAt.${inst.id}`, String(Date.now())) // #3: переживает навигацию
      setScanState('sent')
      setTimeout(() => setScanState('idle'), 120_000) // через ~2 мин кнопка снова активна
    } catch {
      setScanState('err')
      setTimeout(() => setScanState('idle'), 5_000)
    }
  }

  // F-warm-button (ADR-0022): отметить/снять сетап в пачке; «Поставить отмеченные» шлёт ВСЕ разом —
  // движок сам разберёт, какие годны (валидный PENDING вкл. reanchored), невалидные молча пропустит.
  const toggleWarm = (symbol: string) =>
    setWarmSel((s) => {
      const n = new Set(s)
      if (n.has(symbol)) n.delete(symbol)
      else n.add(symbol)
      return n
    })
  const doWarmBatch = async () => {
    if (warmSel.size === 0 || warmBatch === 'busy') return
    const sent = [...warmSel]
    setWarmBatch('busy')
    try {
      await warmApply(inst.id, sent) // ОДНА команда со списком → движок разберёт пачку
      setWarmBatch('sent')
      setWarmSel(new Set())
      const now = Date.now()
      setWarmSentAt((m) => ({ ...m, ...Object.fromEntries(sent.map((c) => [c, now])) }))
      setTimeout(() => setWarmBatch('idle'), 60_000)
      // ⏳→судьба — производная (warmSentAt + время + ордера + вердикт), НЕ таймер (не «тихо гаснет»)
    } catch {
      setWarmBatch('err')
      setTimeout(() => setWarmBatch('idle'), 5_000)
    }
  }

  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const r = await getEngineState(inst.id)
        if (!stop) {
          setResp(r)
          setErr(false)
        }
      } catch {
        if (!stop) setErr(true)
      }
      if (!stop) timer = setTimeout(tick, 5000)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
    }
  }, [inst.id])

  // scout-снимки (вердикт движка per-coin) — для причины «не взято» в стеке. Реже, чем engine_state.
  useEffect(() => {
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const s = await getInstanceScout(inst.id)
        if (!stop) setScoutSnaps(s)
      } catch {
        /* снимков нет — причину просто не покажем, не роняем карточку */
      }
      if (!stop) timer = setTimeout(tick, 20_000)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
    }
  }, [inst.id])

  // Судьба warm-монеты по её вердикту движка (из scout-снимка): человеческая причина «не взято».
  const warmReason = (symbol: string): string | undefined => {
    const snap = scoutSnaps.find((s) => s.symbol === symbol)
    if (!snap) return undefined // снимка нет → причину не знаем (движок мог пропустить по тайму/капу)
    return skipReason(snap)?.label // «уже не годен» / «вход по рынку» / «мимо списка» / …
  }

  // Клик по монете стека → снимок сетапа (symbol,tf) из ЕГО печки → тот же деталь-график, что в Разведке
  // (ScoutDetail: свечи + уровни входов/стоп + факт-слой ордера/позиция из снимка). Только карточка Борса.
  const pickCoin = async (symbol: string, tf: string | null) => {
    setPickErr(null)
    try {
      const snaps = await getInstanceScout(inst.id)
      const hit =
        snaps.find((s) => s.symbol === symbol && (tf == null || s.tf === tf)) ??
        snaps.find((s) => s.symbol === symbol)
      if (hit) setDetail(hit)
      // честно: не «ещё не пришёл» (это подразумевало бы «подожди») — скаут мог перестать отслеживать
      // монету (сетап закоммитился/отработал и ушёл из его находок), пока позиция ещё открыта (F-scout-snap)
      else setPickErr(`${symbol}: скаут сейчас не отслеживает эту монету (сетап отработал/в развитии)`)
    } catch {
      setPickErr(`${symbol}: не удалось получить снимок`)
    }
  }

  const st = resp?.state
  const cap = st?.capital
  const status = st?.status
  const chip = chipOf(status?.state)
  const dd = cap?.dd_pct ?? 0

  return (
    <>
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 p-4 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[85vh] w-full max-w-[980px] flex-col overflow-hidden rounded-card border border-white/10 bg-[#141826] shadow-[0_28px_90px_-16px_rgba(0,0,0,0.9)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-px bg-gradient-to-r from-transparent via-gold/50 to-transparent" />

        {/* ── ФИКСИРОВАННАЯ ШАПКА-ГЕРОЙ ── */}
        <div className="shrink-0 border-b border-white/[0.06] px-6 pb-5 pt-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="mb-1.5 text-[10px] uppercase tracking-[0.2em] text-ash">
                Факт движка · {inst.id.slice(0, 8)}…
              </div>
              <div className="flex items-center gap-3">
                <h2 className="font-serif text-[24px] leading-none text-bone">{inst.client}</h2>
                <span className={`rounded-pill border px-2.5 py-1 text-[11px] ${chip.cls}`}>
                  {chip.label}
                </span>
              </div>
              <div className="mt-3.5">
                <div className="text-[10px] uppercase tracking-[0.2em] text-ash">Equity</div>
                <div className="gild font-serif text-[clamp(28px,2.6vw,36px)] leading-none tnum">
                  {money(cap?.equity)}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-fog">
                  <span>
                    пик <span className="tnum text-mist">{money(cap?.peak)}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    просадка
                    <span className="mini-dd">
                      <i style={{ width: `${Math.min(100, Math.max(0, dd))}%` }} />
                    </span>
                    <span className={`tnum ${dd > 0 ? 'text-copper' : 'text-mist'}`}>
                      {dd.toFixed(2)}%
                    </span>
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-end gap-2">
              {status?.kill_switch && <Flag tone="danger">⚠ KILL-SWITCH</Flag>}
              {status?.alarm && <Flag tone="gold">▲ ТРЕВОГА</Flag>}
              {status?.stale && <Flag tone="muted">данные устарели</Flag>}
              <button
                onClick={onClose}
                className="mt-1 rounded-pill border border-white/10 px-3 py-1.5 text-[13px] text-fog transition-colors hover:border-white/20 hover:text-mist"
              >
                ✕ закрыть
              </button>
            </div>
          </div>
        </div>

        {/* ── СКРОЛЛЯЩЕЕСЯ ТЕЛО ── */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {!st && err && <Placeholder tone="danger">Нет связи с ядром…</Placeholder>}
          {!st && !err && (
            <Placeholder>Ждём данные движка (бот ещё не прислал engine_state)…</Placeholder>
          )}

          {st && (
            <>
              <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Tile label="Открыто позиций" value={String(cap?.open_count ?? 0)} />
                <Tile label="Активных ордеров" value={String(st.orders.length)} />
                <Tile
                  label="Нереализ. P&L"
                  value={signed(cap?.unrealised_pnl)}
                  tone={pnlCls(cap?.unrealised_pnl)}
                />
                <Tile
                  label="Реализ. P&L"
                  value={signed(cap?.realised_pnl)}
                  tone={pnlCls(cap?.realised_pnl)}
                />
              </div>

              {/* S8/ADR-0020: рабочая вселенная динамик-бота (Борс). Персиваль/фикс-набор — stack нет → секции нет */}
              {st.stack && (
                <StackPanel
                  stack={st.stack}
                  onPick={pickCoin}
                  pickErr={pickErr}
                  scanState={scanState}
                  onScan={doScan}
                  warmSel={warmSel}
                  onToggleWarm={toggleWarm}
                  warmBatch={warmBatch}
                  onWarmBatch={doWarmBatch}
                  warmSentAt={warmSentAt}
                  warmReason={warmReason}
                  onWarmClear={(sym) =>
                    setWarmSentAt((m) => {
                      const n = { ...m }
                      delete n[sym]
                      return n
                    })
                  }
                  inOrders={new Set(st.orders.map((o) => o.symbol))}
                />
              )}

              <Section title="Позиции" count={st.positions.length} empty="Открытых позиций нет">
                <DataTable cols={['Монета', 'Сторона', 'Вход', 'Размер', 'P&L']} numFrom={2}>
                  {st.positions.map((p, i) => (
                    <tr key={i} className="hover:bg-white/[0.015]">
                      <Td strong>{p.symbol}</Td>
                      <Td>
                        <SideBadge side={p.side} />
                      </Td>
                      <Td num>{num(p.avg_px)}</Td>
                      <Td num>{num(p.size)}</Td>
                      <Td num tone={pnlCls(p.live_pnl)}>
                        {signed(p.live_pnl)}
                      </Td>
                    </tr>
                  ))}
                </DataTable>
              </Section>

              <Section title="Активные ордера" count={st.orders.length} empty="Активных ордеров нет">
                <DataTable
                  cols={['Монета', 'Сторона', 'Тип', 'Цена', 'Кол-во', 'Статус']}
                  numFrom={3}
                >
                  {st.orders.map((o, i) => (
                    <tr key={i} className="hover:bg-white/[0.015]">
                      <Td strong>{o.symbol}</Td>
                      <Td>
                        <SideBadge side={o.side} />
                      </Td>
                      <Td>{o.type}</Td>
                      <Td num>{num(o.px)}</Td>
                      <Td num>{num(o.qty)}</Td>
                      <Td num>
                        <span className="rounded-pill border border-white/10 px-2 py-0.5 text-[10px] text-mist">
                          {o.status}
                        </span>
                      </Td>
                    </tr>
                  ))}
                </DataTable>
              </Section>

              <Section title="Последние сделки" count={st.trades.length} empty="Сделок пока нет">
                <DataTable cols={['Монета', 'Сторона', 'Кол-во', 'P&L', 'Время']} numFrom={2}>
                  {st.trades.map((t, i) => (
                    <tr key={i} className="hover:bg-white/[0.015]">
                      <Td strong>{t.symbol}</Td>
                      <Td>
                        <SideBadge side={t.side} />
                      </Td>
                      <Td num>{num(t.qty)}</Td>
                      <Td num tone={pnlCls(t.pnl)}>
                        {signed(t.pnl)}
                      </Td>
                      <Td num>{ts(t.ts)}</Td>
                    </tr>
                  ))}
                </DataTable>
              </Section>

              <Section title="События" count={st.events.length} empty="Событий нет">
                <ul>
                  {st.events.map((e, i) => (
                    <li
                      key={i}
                      className="flex items-baseline justify-between gap-4 border-t border-line px-4 py-2.5 text-[12px] first:border-t-0 hover:bg-white/[0.015]"
                    >
                      <span className="min-w-0">
                        <span className="text-mist">{e.kind}</span>
                        {e.detail && <span className="text-fog"> · {e.detail}</span>}
                      </span>
                      <span className="shrink-0 tnum text-ash">{ts(e.ts)}</span>
                    </li>
                  ))}
                </ul>
              </Section>

              <div className="mt-4 flex items-center gap-2 text-[11px] text-ash">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ok" />
                обновляется ~5с · факт движка, не живой тик
                {resp?.received_at ? ` · получено ${ts(resp.received_at).slice(11)}` : ''}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
    {detail && <ScoutDetail snap={detail} onClose={() => setDetail(null)} />}
    </>
  )
}

function Flag({ tone, children }: { tone: 'danger' | 'gold' | 'muted'; children: React.ReactNode }) {
  const cls =
    tone === 'danger'
      ? 'border-danger/50 bg-danger/15 text-danger'
      : tone === 'gold'
        ? 'border-gold/50 bg-gold/15 text-gold'
        : 'border-line bg-white/[0.03] text-ash'
  return (
    <span className={`rounded-pill border px-3 py-1 text-[11px] font-semibold tracking-wide ${cls}`}>
      {children}
    </span>
  )
}

function Tile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-card border border-white/[0.06] bg-[#0d1017] p-3.5">
      <div className="mb-2 text-[10px] uppercase tracking-[0.15em] text-ash">{label}</div>
      <div className={`font-serif text-[clamp(20px,1.7vw,26px)] leading-none tnum ${tone ?? 'text-bone'}`}>
        {value}
      </div>
    </div>
  )
}

function Placeholder({ tone, children }: { tone?: 'danger'; children: React.ReactNode }) {
  return (
    <div
      className={`rounded-card border border-white/[0.06] bg-[#0d1017] py-14 text-center text-[13px] ${
        tone === 'danger' ? 'text-danger' : 'text-ash'
      }`}
    >
      {children}
    </div>
  )
}

// Секция-гармошка: клик по шапке сворачивает/разворачивает тело.
function Section({
  title,
  count,
  empty,
  children,
}: {
  title: string
  count: number
  empty: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="mb-3 overflow-hidden rounded-card border border-white/[0.06] bg-[#0d1017]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left transition-colors hover:bg-white/[0.02]"
      >
        <span className="flex items-center gap-2">
          <span
            className={`text-[10px] text-ash transition-transform duration-300 ${open ? 'rotate-90' : ''}`}
          >
            ▸
          </span>
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist">
            {title}
          </span>
        </span>
        <span className="rounded-pill bg-white/[0.05] px-2 py-0.5 text-[11px] text-ash tnum">
          {count}
        </span>
      </button>
      {/* плавная гармошка: анимируем grid-template-rows 0fr↔1fr (высота-auto не анимируется) */}
      <div
        className={`grid transition-[grid-template-rows] duration-[350ms] ease-out ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          {count === 0 ? (
            <div className="border-t border-line px-4 py-6 text-center text-[12px] text-steel">
              — {empty} —
            </div>
          ) : (
            <div className="overflow-x-auto">{children}</div>
          )}
        </div>
      </div>
    </div>
  )
}

function DataTable({
  cols,
  numFrom,
  children,
}: {
  cols: string[]
  numFrom: number
  children: React.ReactNode
}) {
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr>
          {cols.map((c, i) => (
            <th
              key={c}
              className={`border-t border-line px-4 py-2 text-[10px] font-medium uppercase tracking-[0.08em] text-ash ${
                i >= numFrom ? 'text-right' : 'text-left'
              }`}
            >
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  )
}

function Td({
  children,
  strong,
  num,
  tone,
}: {
  children: React.ReactNode
  strong?: boolean
  num?: boolean
  tone?: string
}) {
  return (
    <td
      className={`border-t border-line px-4 py-2.5 tnum ${num ? 'text-right' : 'text-left'} ${
        tone ?? (strong ? 'font-semibold text-bone' : 'text-silver')
      }`}
    >
      {children}
    </td>
  )
}

function SideBadge({ side }: { side: string }) {
  const long = /buy|long/i.test(side)
  const short = /sell|short/i.test(side)
  const cls = long
    ? 'border-ok/40 text-ok'
    : short
      ? 'border-danger/40 text-danger'
      : 'border-line text-fog'
  return <span className={`rounded-pill border px-2 py-0.5 text-[10px] ${cls}`}>{side || '—'}</span>
}

// S8/ADR-0020: стек рабочих монет динамик-бота из печки. Чип «в стеке k · кап N» — ЧЕСТЕН при сжатии
// капа на живую (EDIT 2 Куратора: перебор подсвечивается медью, никого не выгоняем — естественное убытие).
const SCAN_LABEL: Record<string, string> = {
  idle: '⟳ Сканировать сейчас',
  busy: '…отправляю',
  sent: '✓ скан идёт · ~1-2 мин · можно уходить',
  err: 'не прошло — ещё раз?',
}

// Мелкий счётчик до следующей 4h-границы (закрытие 4h-свечи = плановый автоскан: пересбор сетапов/
// вселенной + самоход). UTC-сетка 4h (00/04/08/12/16/20), обновляется раз в 30с. Просьба Оператора —
// «в уголочке», чтобы видеть, когда следующее плановое обновление, не гадая руками.
function NextBoundary() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(id)
  }, [])
  const FOUR_H = 4 * 60 * 60_000
  const next = Math.ceil((now + 1) / FOUR_H) * FOUR_H
  const left = next - now
  const h = Math.floor(left / 3_600_000)
  const m = Math.floor((left % 3_600_000) / 60_000)
  const at = new Date(next).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return (
    <span
      className="font-normal normal-case tracking-normal text-[10.5px] text-ash"
      title="следующее закрытие 4h-свечи (UTC-сетка 00/04/08/12/16/20): плановый автоскан — пересбор сетапов и вселенной + авто-подхват (самоход). Ручной warm_apply/⏳ исполняется быстрее, на 15m-тике."
    >
      след. скан ~{at} · через {h > 0 ? `${h}ч ` : ''}
      {m}м
    </span>
  )
}

function StackPanel({
  stack,
  onPick,
  pickErr,
  scanState = 'idle',
  onScan,
  warmSel,
  onToggleWarm,
  warmBatch = 'idle',
  onWarmBatch,
  warmSentAt,
  warmReason,
  onWarmClear,
  inOrders,
}: {
  stack: EngineStack
  onPick?: (symbol: string, tf: string | null) => void
  pickErr?: string | null
  scanState?: 'idle' | 'busy' | 'sent' | 'err'
  onScan?: () => void
  warmSel?: Set<string>
  onToggleWarm?: (symbol: string) => void
  warmBatch?: 'idle' | 'busy' | 'sent' | 'err'
  onWarmBatch?: () => void
  warmSentAt?: Record<string, number>
  warmReason?: (symbol: string) => string | undefined
  onWarmClear?: (symbol: string) => void
  inOrders?: Set<string>
}) {
  const over = stack.count > stack.cap
  return (
    <div className="mb-3 overflow-hidden rounded-card border border-white/[0.06] bg-[#0d1017]">
      <div className="flex items-center justify-between gap-2 px-4 py-2.5">
        <span className="flex items-center gap-2.5">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist">
            Стек · рабочая вселенная
          </span>
          <NextBoundary />
        </span>
        <span className="flex items-center gap-2">
          {onScan && (
            <button
              onClick={onScan}
              disabled={scanState === 'busy' || scanState === 'sent'}
              title="пересканировать печку этого бота прямо сейчас (не ждать 4h/1h-границы): свежие свечи, сетапы и графики"
              className={`rounded-pill border px-2 py-0.5 text-[11px] transition-colors ${
                scanState === 'sent'
                  ? 'border-ok/40 bg-ok/10 text-ok'
                  : scanState === 'err'
                    ? 'border-danger/40 bg-danger/10 text-danger'
                    : 'border-line text-fog hover:border-white/25 hover:text-mist'
              }`}
            >
              {SCAN_LABEL[scanState]}
            </button>
          )}
          {onWarmBatch && ((warmSel?.size ?? 0) > 0 || warmBatch !== 'idle') && (
            <button
              onClick={onWarmBatch}
              disabled={warmBatch === 'busy' || warmBatch === 'sent'}
              title="Поставить в ордера все отмеченные сетапы разом. Движок сам разберёт: ставит только годные (валидный PENDING, вкл. пере-якорь), невалидные молча пропустит. Исполнение — на ближайшем 15m-тике."
              className={`rounded-pill border px-2.5 py-0.5 text-[11px] transition-colors ${
                warmBatch === 'sent'
                  ? 'border-ok/40 bg-ok/10 text-ok'
                  : warmBatch === 'err'
                    ? 'border-danger/40 bg-danger/10 text-danger'
                    : 'border-copper/45 bg-copper/10 text-copper hover:border-copper/70'
              }`}
            >
              {warmBatch === 'sent'
                ? '✓ запрошено'
                : warmBatch === 'busy'
                  ? '…отправляю'
                  : warmBatch === 'err'
                    ? 'не прошло — ещё раз?'
                    : `Поставить отмеченные · ${warmSel?.size ?? 0}`}
            </button>
          )}
          <span
            className={`rounded-pill border px-2 py-0.5 text-[11px] tnum ${
              over ? 'border-copper/45 bg-copper/10 text-copper' : 'border-line text-ash'
            }`}
          >
            в стеке {stack.count} · кап {stack.cap}
          </span>
        </span>
      </div>
      {stack.items.length === 0 ? (
        <div className="border-t border-line px-4 py-6 text-center text-[12px] text-steel">
          — стек пуст: печка ещё не дала сетапов —
        </div>
      ) : (
        <div className="overflow-x-auto">
          <DataTable cols={['Монета', 'Стадия', 'Скор', 'ТФ', onToggleWarm ? 'В пачку' : '']} numFrom={2}>
            {stack.items.map((it, i) => (
              <tr
                key={i}
                className={
                  onPick ? 'cursor-pointer hover:bg-white/[0.035]' : 'hover:bg-white/[0.015]'
                }
                onClick={onPick ? () => onPick(it.symbol, it.tf) : undefined}
                title={onPick ? 'открыть график сетапа (уровни + ордера)' : undefined}
              >
                <Td strong>
                  {it.symbol}
                  {onPick && <span className="ml-1.5 text-ash">↗</span>}
                </Td>
                <Td>
                  <StageBadge stage={it.stage} />
                </Td>
                <Td num tone="text-copper">
                  {it.score ?? '—'}
                </Td>
                <Td num>{it.tf ?? '—'}</Td>
                <Td num>
                  {onToggleWarm && (
                    <WarmCell
                      inOrders={inOrders?.has(it.symbol) ?? false}
                      sentAt={warmSentAt?.[it.symbol]}
                      reason={warmReason?.(it.symbol)}
                      selected={warmSel?.has(it.symbol) ?? false}
                      onToggle={() => onToggleWarm(it.symbol)}
                      onClear={() => onWarmClear?.(it.symbol)}
                    />
                  )}
                </Td>
              </tr>
            ))}
          </DataTable>
        </div>
      )}
      {pickErr && (
        <div className="border-t border-line px-4 py-2 text-[11px] text-copper">{pickErr}</div>
      )}
    </div>
  )
}

// Судьба отмеченного сетапа (жалоба Оператора «после ⏳ ничего не пишется»): в работе (поставлен) /
// ⏳ ждёт тик / ✗ не взято + причина (вердикт движка) / чек-бокс. Причина — из scout-снимка; нет
// снимка → просто «не взято» (движок пропустил по тайму/капу). Клик по «не взято» → отметить снова.
function WarmCell({
  inOrders,
  sentAt,
  reason,
  selected,
  onToggle,
  onClear,
}: {
  inOrders: boolean
  sentAt?: number
  reason?: string
  selected: boolean
  onToggle: () => void
  onClear: () => void
}) {
  if (inOrders)
    return (
      <span
        className="inline-flex items-center gap-1 text-[10px] text-ok"
        title="движок поставил — есть живые ордера (см. раздел «Ордера» ниже)"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />в работе
      </span>
    )
  if (sentAt != null) {
    if (Date.now() - sentAt < WARM_TICK_MS)
      return (
        <span
          className="hourglass text-[13px]"
          title="отправлено · ждёт ближайший 15m-тик; движок поставит, если сетап годен"
        >
          ⏳
        </span>
      )
    // тик прошёл, в ордера не попал → движок НЕ взял. Показываем причину (не молчим).
    return (
      <span
        role="button"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation()
          onClear()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.stopPropagation()
            e.preventDefault()
            onClear()
          }
        }}
        title={`движок не взял на тике${reason ? ` — ${reason}` : ' (пропустил)'} · клик — отметить снова`}
        className="inline-flex cursor-pointer items-center gap-1 rounded-pill border border-steel/40 px-1.5 text-[10px] text-steel hover:border-fog/40"
      >
        ✗ не взято{reason ? `: ${reason}` : ''}
      </span>
    )
  }
  return (
    <span
      role="checkbox"
      aria-checked={selected}
      tabIndex={0}
      onClick={(e) => {
        e.stopPropagation()
        onToggle()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.stopPropagation()
          e.preventDefault()
          onToggle()
        }
      }}
      title="Отметить сетап в пачку (кнопка «Поставить отмеченные» вверху). Движок сам проверит годность на тике."
      className={`inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded border text-[10px] transition-colors ${
        selected
          ? 'border-copper bg-copper/20 text-copper'
          : 'border-line text-transparent hover:border-copper/50'
      }`}
    >
      ✓
    </span>
  )
}

function StageBadge({ stage }: { stage: string | null }) {
  const s = stage ?? ''
  const cls =
    s === 'ready'
      ? 'border-gold/45 bg-gold/10 text-gold'
      : s === 'tracking'
        ? 'border-copper/40 bg-copper/10 text-copper'
        : s === 'forming'
          ? 'border-line text-fog'
          : 'border-line text-ash'
  const label =
    s === 'ready' ? 'готов' : s === 'tracking' ? 'отслеж.' : s === 'forming' ? 'формир.' : s || '—'
  return <span className={`rounded-pill border px-2 py-0.5 text-[10px] ${cls}`}>{label}</span>
}
