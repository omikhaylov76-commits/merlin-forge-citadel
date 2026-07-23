import { useEffect, useState } from 'react'
import { Chip, PageHead, Toolbar } from '@/components/ui/page'
import { Badge } from '@/components/ui/badge'
import {
  getFleetInstances,
  getSignalJournal,
  visibleScoutInstances,
  type SignalJournalEvent,
} from '@/lib/api'
import { useAsync } from '@/lib/useAsync'

// Экран «Сигналы» (порция №3, Этап 1 переката 1-to-N): read-only лента Сигнального журнала —
// каждое решение ядра-характера как строгое событие (товарная запись для повтора Этапом 2).
// data/setup_id — недоверенный ввод бота: рендер ТОЛЬКО текстом (React экранирует), без HTML.

const SELECTED_KEY = 'mfc.signals.selected' // последний выбранный бот переживает перезагрузку
const REFRESH_MS = 10_000 // авто-обновление ленты (каденция деривера ~10с)

// Русская лексика типов — вычисляется КОНСОЛЬЮ из фактов (Контракт остаётся чистым).
type Tone = 'neutral' | 'live' | 'pause' | 'alarm' | 'gold'
const KIND_RU: Record<SignalJournalEvent['kind'], { label: string; tone: Tone }> = {
  setup_detected: { label: 'найден', tone: 'neutral' },
  setup_placed: { label: 'поставлен', tone: 'live' },
  leg_filled: { label: 'нога залита', tone: 'live' },
  leg_exit: { label: 'выход ноги', tone: 'live' },
  setup_ended: { label: 'завершён', tone: 'pause' },
  trade_closed: { label: 'сделка закрыта', tone: 'gold' },
  service: { label: 'служебное', tone: 'alarm' },
}

const fmtTs = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const fmtNum = (v: unknown) =>
  typeof v === 'number' ? (Math.abs(v) >= 1 ? v.toLocaleString('ru-RU') : String(v)) : String(v)

// Компакт содержимого события: главные поля по kind, остальное не тащим (детали — этап читалки).
function summary(e: SignalJournalEvent): string {
  const d = e.data ?? {}
  const num = (k: string) => (d[k] != null ? fmtNum(d[k]) : null)
  switch (e.kind) {
    case 'setup_detected': {
      const en = (d.entries ?? {}) as Record<string, unknown>
      const legs = ['0.382', '0.5', '0.618'].map((k) => (en[k] != null ? fmtNum(en[k]) : '—')).join(' / ')
      return `${d.side ?? ''} · ноги ${legs} · стоп ${num('stop') ?? '—'}`
    }
    case 'setup_placed':
      return String(d.detail ?? 'сетка выставлена на биржу')
    case 'leg_filled':
      return `нога ${d.entry_level ?? '?'} · запрошено ${num('requested_price') ?? '—'} × ${num('requested_qty') ?? '—'}`
    case 'leg_exit':
      return `${d.role === 'stp' ? 'стоп' : 'тейк'} · нога ${d.lv ?? '?'} · объём ${num('qty') ?? '—'}`
    case 'setup_ended':
      return `причина: ${d.reason ?? '—'}`
    case 'trade_closed':
      return `вход ${num('avg_entry') ?? '—'} → выход ${num('avg_exit') ?? '—'} · P&L ${num('closed_pnl') ?? '—'}`
    case 'service':
      return `${d.raw ?? '—'}${d.detail ? ` · ${d.detail}` : ''}`
  }
}

export function Signals() {
  const fleet = useAsync(getFleetInstances, [])
  const [selected, setSelected] = useState<string | null>(
    () => localStorage.getItem(SELECTED_KEY) || null,
  )
  const instances = visibleScoutInstances(fleet.data ?? [])
  // авто-выбор первого видимого бота (Борс), когда список приехал и выбора нет
  useEffect(() => {
    if (!selected && instances.length > 0) setSelected(instances[0].id)
  }, [selected, instances])
  useEffect(() => {
    if (selected) localStorage.setItem(SELECTED_KEY, selected)
  }, [selected])

  const feed = useAsync(
    () => (selected ? getSignalJournal(selected) : Promise.resolve([])),
    [selected],
  )
  useEffect(() => {
    const id = setInterval(() => feed.reload(), REFRESH_MS)
    return () => clearInterval(id)
  }, [feed.reload])

  const rows = feed.data ?? []
  const kinds = new Set(rows.map((r) => r.kind))

  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Журналы"
        title="Сигналы"
        desc="сигнальный журнал ядра-характера — каждое решение как событие (Этап 1 переката 1-to-N)"
        action={
          instances.length > 0 ? (
            <label className="flex items-center gap-2 text-[12px] text-fog">
              журнал бота
              <select
                value={selected ?? ''}
                onChange={(e) => setSelected(e.target.value)}
                className="rounded-pill border border-line bg-card px-3 py-1.5 text-[12px] text-fog"
              >
                {instances.map((i) => (
                  <option key={i.id} value={i.id}>
                    ◆ {i.client} · {i.id.slice(0, 8)}…
                  </option>
                ))}
              </select>
            </label>
          ) : undefined
        }
      />
      <Toolbar>
        <Chip active>Все события ({rows.length})</Chip>
        <Chip>{kinds.has('setup_placed') ? '● ' : ''}постановки</Chip>
        <Chip>{kinds.has('trade_closed') ? '● ' : ''}финалы</Chip>
      </Toolbar>

      {feed.loading && rows.length === 0 && (
        <div className="rounded-card border border-line bg-card p-8 text-center text-fog">
          Загружаю журнал…
        </div>
      )}
      {feed.error && (
        <div className="rounded-card border border-line bg-card p-8 text-center text-fog">
          Журнал не отвечает: {String(feed.error)}
        </div>
      )}
      {!feed.loading && !feed.error && rows.length === 0 && (
        <div className="rounded-card border border-line bg-card p-8 text-center text-fog">
          — журнал пуст: бот ещё не прислал событий (канал включается деплоем, Борс первым) —
        </div>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-card border border-line bg-card">
          <table className="dt">
            <thead>
              <tr>
                <th className="num">№</th>
                <th>Время</th>
                <th>Событие</th>
                <th>Сетап</th>
                <th>Содержимое</th>
                <th className="num">Источник</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const k = KIND_RU[r.kind] ?? { label: r.kind, tone: 'neutral' as const }
                return (
                  <tr key={`${r.src.table}:${r.src.id}`}>
                    <td className="tnum text-fog">{r.seq}</td>
                    <td className="tnum text-fog">{fmtTs(r.ts)}</td>
                    <td>
                      <Badge tone={k.tone}>{k.label}</Badge>
                    </td>
                    <td className="font-semibold text-bone">{r.setup_id}</td>
                    <td className="text-fog">{summary(r)}</td>
                    <td className="tnum text-fog">
                      {r.src.table}#{r.src.id}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
