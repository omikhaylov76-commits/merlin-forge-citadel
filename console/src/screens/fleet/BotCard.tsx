import { useEffect, useState } from 'react'
import { getEngineState, type EngineStateResp, type FleetInstance } from '@/lib/api'

// Карточка бота (S7): клик по строке Флота → факт-слой движка (статус/kill-switch/тревога · equity/
// пик/просадка/PnL · ПОЗИЦИИ · АКТИВНЫЕ ОРДЕРА · последние сделки/события). Автообновление ~5с.
// Данные — engine_state readout ядра (картридж пушит каденцией телеметрии). Живого тика нет (ADR-0001).

const num = (n?: number) => (n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 6 }))
const money = (n?: number) =>
  n == null ? '—' : '$' + n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
const pnlTone = (n: number) => (n > 0 ? 'text-ok' : n < 0 ? 'text-danger' : 'text-fog')
const ts = (s?: string) => (s ? s.slice(0, 19).replace('T', ' ') : '—')

export function BotCard({ inst, onClose }: { inst: FleetInstance; onClose: () => void }) {
  const [resp, setResp] = useState<EngineStateResp | null>(null)
  const [err, setErr] = useState(false)

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

  const st = resp?.state
  const cap = st?.capital
  const status = st?.status

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/70 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[92vh] w-full max-w-[1080px] overflow-y-auto rounded-card border border-line bg-floating p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-serif text-[22px] text-bone">{inst.client}</h2>
              <span className="rounded-pill border border-line px-2 text-[11px] text-ash">
                {inst.id.slice(0, 8)}…
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
              <span className="rounded-pill border border-line px-2 text-fog">
                {status?.state ?? inst.status}
              </span>
              {status?.kill_switch && (
                <span className="rounded-pill border border-danger/40 px-2 text-danger">
                  kill-switch
                </span>
              )}
              {status?.alarm && (
                <span className="rounded-pill border border-gold/40 px-2 gild">тревога</span>
              )}
              {status?.stale && (
                <span className="rounded-pill border border-line px-2 text-ash">
                  данные устарели
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-pill border border-line px-3 py-1 text-[13px] text-fog hover:text-mist"
          >
            ✕ закрыть
          </button>
        </div>

        {!st && err && (
          <div className="py-12 text-center text-[13px] text-danger">Нет связи с ядром…</div>
        )}
        {!st && !err && (
          <div className="py-12 text-center text-[13px] text-ash">
            Ждём данные движка (бот ещё не прислал engine_state)…
          </div>
        )}

        {st && (
          <>
            <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 text-[12px]">
              <Metric label="Equity" value={money(cap?.equity)} />
              <Metric label="Пик" value={money(cap?.peak)} />
              <Metric label="Просадка" value={cap ? cap.dd_pct.toFixed(2) + '%' : '—'} />
              <Metric label="Открыто" value={String(cap?.open_count ?? '—')} />
              <Metric
                label="Нереализ. P&L"
                value={money(cap?.unrealised_pnl)}
                tone={pnlTone(cap?.unrealised_pnl ?? 0)}
              />
              <Metric
                label="Реализ. P&L"
                value={money(cap?.realised_pnl)}
                tone={pnlTone(cap?.realised_pnl ?? 0)}
              />
            </div>

            <Section title="Позиции" count={st.positions.length} empty="Открытых позиций нет">
              <Table head={['Монета', 'Сторона', 'Вход', 'Размер', 'P&L']}>
                {st.positions.map((p, i) => (
                  <tr key={i} className="border-t border-line/60">
                    <Td b>{p.symbol}</Td>
                    <Td>{p.side}</Td>
                    <Td>{num(p.avg_px)}</Td>
                    <Td>{num(p.size)}</Td>
                    <td className={`px-3 py-2 tnum ${pnlTone(p.live_pnl)}`}>{num(p.live_pnl)}</td>
                  </tr>
                ))}
              </Table>
            </Section>

            <Section
              title="Активные ордера"
              count={st.orders.length}
              empty="Активных ордеров нет"
            >
              <Table head={['Монета', 'Сторона', 'Тип', 'Цена', 'Кол-во', 'Статус']}>
                {st.orders.map((o, i) => (
                  <tr key={i} className="border-t border-line/60">
                    <Td b>{o.symbol}</Td>
                    <Td>{o.side}</Td>
                    <Td>{o.type}</Td>
                    <Td>{num(o.px)}</Td>
                    <Td>{num(o.qty)}</Td>
                    <Td>{o.status}</Td>
                  </tr>
                ))}
              </Table>
            </Section>

            <Section title="Последние сделки" count={st.trades.length} empty="Сделок пока нет">
              <Table head={['Монета', 'Сторона', 'Кол-во', 'P&L', 'Время']}>
                {st.trades.map((t, i) => (
                  <tr key={i} className="border-t border-line/60">
                    <Td b>{t.symbol}</Td>
                    <Td>{t.side}</Td>
                    <Td>{num(t.qty)}</Td>
                    <td className={`px-3 py-2 tnum ${pnlTone(t.pnl)}`}>{num(t.pnl)}</td>
                    <Td>{ts(t.ts)}</Td>
                  </tr>
                ))}
              </Table>
            </Section>

            <Section title="События" count={st.events.length} empty="Событий нет">
              <div className="space-y-1 px-3 py-2 text-[11px] text-ash">
                {st.events.map((e, i) => (
                  <div key={i}>
                    <span className="text-fog">{e.kind}</span> · {ts(e.ts)} · {e.detail}
                  </div>
                ))}
              </div>
            </Section>

            <div className="mt-3 text-[11px] text-ash">
              обновляется ~5с · факт движка, не живой тик
              {resp?.received_at ? ` · получено ${ts(resp.received_at).slice(11)}` : ''}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-card border border-line bg-card p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-ash">{label}</div>
      <div className={`mt-0.5 tnum ${tone ?? 'text-fog'}`}>{value}</div>
    </div>
  )
}

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
  return (
    <div className="mb-3 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <span className="text-[12px] font-semibold uppercase tracking-wide text-mist">{title}</span>
        <span className="text-[11px] text-ash">{count}</span>
      </div>
      {count === 0 ? (
        <div className="px-3 py-4 text-center text-[12px] text-ash">{empty}</div>
      ) : (
        <div className="overflow-x-auto">{children}</div>
      )}
    </div>
  )
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="text-left text-[11px] text-ash">
          {head.map((h) => (
            <th key={h} className="px-3 py-2 font-normal">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  )
}

function Td({ children, b }: { children: React.ReactNode; b?: boolean }) {
  return <td className={`px-3 py-2 tnum ${b ? 'font-semibold text-bone' : 'text-ash'}`}>{children}</td>
}
