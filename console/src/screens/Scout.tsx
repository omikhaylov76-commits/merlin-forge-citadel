import { useEffect, useMemo, useState } from 'react'
import { Chip, PageHead, Toolbar } from '@/components/ui/page'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useAsync } from '@/lib/useAsync'
import { type ScoutSnapshot } from '@/lib/api'
import { boardColumn, COLUMNS, loadScoutBoard, sortSnaps } from '@/lib/scout'
import { ScoutCard } from './scout/ScoutCard'
import { ScoutDetail } from './scout/ScoutDetail'
import { ProducerLabel, StaleBadge } from './scout/Badges'

// Экран Разведка (#53, макет kuznitsa-walkthrough Экран 1): ЖИВОЙ readout /v1/instances/{id}/scout.
// Консоль = ДИСПЛЕЙ снимка скаута; производные (%-до-входа/свежесть) — на фронте, честно подписаны.
export function Scout() {
  const board = useAsync(loadScoutBoard, [])
  const [selected, setSelected] = useState<string | null>(null)
  const [onlyReady, setOnlyReady] = useState(false)
  const [minScore, setMinScore] = useState(false)
  const [detail, setDetail] = useState<ScoutSnapshot | null>(null)

  // дефолт селектора = инстанс с самыми свежими снимками (режим представителя, ADR-0016 в.6);
  // сброс, если выбранный инстанс исчез из обновлённого флота (иначе показ пустого не того бота).
  useEffect(() => {
    if (!board.data) return
    const ids = board.data.instances.map((i) => i.id)
    if (selected == null || !ids.includes(selected)) {
      setSelected(board.data.freshest ?? board.data.instances[0]?.id ?? null)
    }
  }, [board.data, selected])

  const instances = board.data?.instances ?? []
  const byInstance = board.data?.byInstance ?? {}
  const hasAnyData = Object.values(byInstance).some((s) => s.length > 0)
  const snaps = selected ? (byInstance[selected] ?? []) : []
  const producer = snaps[0]?.producer ?? '—'
  const freshest = snaps.reduce<ScoutSnapshot | null>(
    (a, s) => (!a || Date.parse(s.scan_ts) > Date.parse(a.scan_ts) ? s : a),
    null,
  )

  const byCol = useMemo(() => {
    let list = snaps
    if (onlyReady) list = list.filter((s) => boardColumn(s) === 'ready')
    if (minScore) list = list.filter((s) => s.score >= 35)
    const m: Record<string, ScoutSnapshot[]> = { forming: [], tracking: [], ready: [], committed: [] }
    for (const s of sortSnaps(list)) m[boardColumn(s)].push(s)
    return m
  }, [snaps, onlyReady, minScore])

  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Кузница"
        title="Разведка"
        desc={
          board.loading
            ? 'загрузка…'
            : board.error
              ? '— · нет связи с ядром'
              : `снимок скаута · ТФ 4h/1h · ботов: ${instances.length}`
        }
        action={
          instances.length > 0 ? (
            <select
              value={selected ?? ''}
              onChange={(e) => {
                setSelected(e.target.value)
                setDetail(null)
              }}
              className="rounded-pill border border-line bg-card px-3 py-1.5 text-[12px] text-fog"
            >
              {instances.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.client} · {i.id.slice(0, 8)}…
                </option>
              ))}
            </select>
          ) : undefined
        }
      />
      <Toolbar>
        <Chip active={onlyReady} onClick={() => setOnlyReady((v) => !v)}>
          Только готовые
        </Chip>
        <Chip active={minScore} onClick={() => setMinScore((v) => !v)}>
          Скор ≥ 35
        </Chip>
        <span className="ml-1">
          <ProducerLabel producer={producer} />
        </span>
        {freshest && <StaleBadge snap={freshest} />}
      </Toolbar>

      {board.loading ? (
        <SkeletonBoard />
      ) : board.error ? (
        <EmptyState kind="error" msg={board.error.message} onRetry={board.reload} />
      ) : !hasAnyData && snaps.length === 0 ? (
        <EmptyState kind="silent" />
      ) : snaps.length === 0 ? (
        <EmptyState kind="quiet" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {COLUMNS.map((col) => (
            <div
              key={col.key}
              className={`rounded-card border bg-card p-3 ${
                col.key === 'ready' ? 'border-gold/25' : 'border-line'
              }`}
            >
              <div className="mb-3 flex items-center justify-between px-1">
                <span className="text-[12px] font-semibold uppercase tracking-wide text-mist">
                  {col.label}
                </span>
                <span className="text-[11px] text-ash">{byCol[col.key].length}</span>
              </div>
              <div className="flex flex-col gap-2">
                {byCol[col.key].map((s) => (
                  <ScoutCard key={s.symbol + s.tf} snap={s} onOpen={() => setDetail(s)} />
                ))}
                {byCol[col.key].length === 0 && (
                  <div className="px-1 py-2 text-[11px] text-ash">пусто</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {detail && <ScoutDetail snap={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}

function SkeletonBoard() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {COLUMNS.map((c) => (
        <div key={c.key} className="animate-pulse rounded-card border border-line bg-card p-3">
          <div className="mb-3 h-3 w-24 rounded bg-panel" />
          <div className="flex flex-col gap-2">
            <div className="h-16 rounded-card bg-panel" />
            <div className="h-16 rounded-card bg-panel" />
          </div>
        </div>
      ))}
    </div>
  )
}

// Три РАЗНЫХ пустых состояния (директива #53 п.7) + ошибка связи.
function EmptyState({
  kind,
  msg,
  onRetry,
}: {
  kind: 'error' | 'silent' | 'quiet'
  msg?: string
  onRetry?: () => void
}) {
  if (kind === 'error') {
    return (
      <Card className="flex flex-col items-center gap-3 py-12 text-center">
        <div className="text-[15px] text-danger">Нет связи с ядром</div>
        <div className="text-[12px] text-ash">{msg ?? 'запрос не прошёл'}</div>
        <Button onClick={onRetry}>Повторить</Button>
      </Card>
    )
  }
  if (kind === 'silent') {
    return (
      <Card className="flex flex-col items-center gap-2 py-12 text-center">
        <div className="text-[15px] text-mist">Скаут молчит — данных нет</div>
        <div className="max-w-md text-[12px] text-ash">
          Ни один бот флота ещё не прислал снимков разведки (скаут не включён либо не сканировал).
          Как пойдут снимки — доска заполнится сама.
        </div>
      </Card>
    )
  }
  return (
    <Card className="flex flex-col items-center gap-2 py-12 text-center">
      <div className="text-[15px] text-mist">Рынок тихий — сетапов нет</div>
      <div className="max-w-md text-[12px] text-ash">
        Скаут этого бота на связи, но сейчас подходящих сетапов не нашёл. Это норма — сетапы на 4h
        бывают не каждый час.
      </div>
    </Card>
  )
}
