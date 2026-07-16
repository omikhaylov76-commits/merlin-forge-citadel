import { useEffect, useMemo, useState } from 'react'
import { PageHead } from '@/components/ui/page'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useAsync } from '@/lib/useAsync'
import {
  enqueueScreenerRun,
  getFleetInstances,
  getScreenerRun,
  type ScreenerFinding,
  type ScreenerRun,
} from '@/lib/api'

// Экран «Скринер» (С7-2б): оператор задаёт параметры → «Подобрать и сканировать» → ядро ставит
// команду инстансу-представителю (Галахад) → картридж гоняет скринер отдельным процессом и пушит
// результат → здесь опрашиваем прогон и рисуем таблицу. Возраст/оборот — отсевы Этапа A; импульс — новое.

type Params = {
  min_age_days: number
  min_turnover_usd: number
  k: number
  days: number
  universe_max: number
}

const DEFAULTS: Params = {
  min_age_days: 180,
  min_turnover_usd: 5_000_000,
  k: 1.5,
  days: 14,
  universe_max: 150,
}

const FIELDS: { key: keyof Params; label: string; step?: number }[] = [
  { key: 'min_age_days', label: 'Возраст ≥ (дней)' },
  { key: 'min_turnover_usd', label: 'Оборот 24ч ≥ ($)' },
  { key: 'k', label: 'Импульс ≥ (×среднего)', step: 0.1 },
  { key: 'days', label: 'Окно среднего (дней)' },
  { key: 'universe_max', label: 'Вселенная (top по обороту)' },
]

const RUNNING = (s?: string) => s === 'queued' || s === 'running'

export function Screener() {
  const fleet = useAsync(getFleetInstances, [])
  const [selected, setSelected] = useState<string | null>(null)
  const [params, setParams] = useState<Params>(DEFAULTS)
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<ScreenerRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // дефолт инстанса-представителя = Галахад (у него включён скаут), иначе первый
  useEffect(() => {
    if (!fleet.data || selected) return
    const gal = fleet.data.find((i) => i.client.includes('Галахад'))
    setSelected(gal?.id ?? fleet.data[0]?.id ?? null)
  }, [fleet.data, selected])

  // опрос статуса прогона до done|error (каждые 3с)
  useEffect(() => {
    if (!runId) return
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      try {
        const r = await getScreenerRun(runId)
        if (stop) return
        setRun(r)
        if (!RUNNING(r.status)) {
          setBusy(false)
          return
        }
      } catch {
        /* транзиент — продолжаем опрос */
      }
      if (!stop) timer = setTimeout(tick, 3000)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
    }
  }, [runId])

  const start = async () => {
    if (!selected || busy) return
    setError(null)
    setBusy(true)
    setRun(null)
    try {
      const { run_id } = await enqueueScreenerRun(selected, { ...params, tfs: ['4h', '1h'] })
      setRunId(run_id)
    } catch {
      setBusy(false)
      setError('Не удалось запустить прогон — проверь связь с ядром')
    }
  }

  const set = (k: keyof Params, v: string) =>
    setParams((p) => ({ ...p, [k]: v === '' ? 0 : Number(v) }))

  const findings = run?.findings ?? []
  const selectedRows = useMemo(
    () =>
      [...findings]
        .filter((f) => f.selected)
        .sort((a, b) => (b.impulse_ratio ?? 0) - (a.impulse_ratio ?? 0)),
    [findings],
  )
  const rejectedRows = useMemo(
    () =>
      [...findings]
        .filter((f) => !f.selected)
        .sort((a, b) => (b.impulse_ratio ?? 0) - (a.impulse_ratio ?? 0)),
    [findings],
  )
  const summary = (run?.summary ?? {}) as Record<string, number>

  return (
    <div className="mx-auto max-w-[1560px]">
      <PageHead
        eyebrow="Кузница"
        title="Скринер"
        desc="Подбор монет по параметрам: возраст · оборот · импульс объёма → скан на 4h и 1h"
        action={
          fleet.data && fleet.data.length > 0 ? (
            <select
              value={selected ?? ''}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-pill border border-line bg-card px-3 py-1.5 text-[12px] text-fog"
            >
              {fleet.data.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.client} · {i.id.slice(0, 8)}…
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      <Card className="mb-4 p-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {FIELDS.map((f) => (
            <label key={f.key} className="flex flex-col gap-1 text-[11px] text-ash">
              {f.label}
              <input
                type="number"
                step={f.step ?? 1}
                value={params[f.key]}
                onChange={(e) => set(f.key, e.target.value)}
                className="rounded-card border border-line bg-panel px-2 py-1.5 text-[13px] text-fog tnum"
              />
            </label>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={start} disabled={busy || !selected}>
            {busy ? 'Идёт подбор…' : 'Подобрать и сканировать'}
          </Button>
          {busy && (
            <span className="text-[12px] text-ash">
              скринер тянет Bybit (RPS 1) — обычно 2–5 минут, статус: {run?.status ?? 'запуск'}
            </span>
          )}
          {error && <span className="text-[12px] text-danger">{error}</span>}
        </div>
      </Card>

      {run?.status === 'error' && (
        <Card className="mb-4 border-danger/30 p-4 text-[13px] text-danger">
          Прогон завершился ошибкой{summary.error ? `: ${summary.error}` : ''}. Попробуй ещё раз.
        </Card>
      )}

      {run?.status === 'done' && (
        <>
          <div className="mb-3 flex flex-wrap gap-4 text-[12px] text-ash">
            <span>
              вселенная <b className="text-fog tnum">{fnl(run, 'universe_total')}</b>
            </span>
            <span>
              klines <b className="text-fog tnum">{fnl(run, 'klines_fetched')}</b>
            </span>
            <span>
              Этап A прошли <b className="text-fog tnum">{summary.passed_stage_a ?? '—'}</b>
            </span>
            <span>
              импульс взято <b className="gild tnum">{summary.selected_count ?? selectedRows.length}</b>
            </span>
          </div>

          <FindingsTable title="Взятые (импульс)" rows={selectedRows} gold empty="Никто не прошёл импульс-порог" />
          <div className="h-4" />
          <FindingsTable title="Отсеяны" rows={rejectedRows} empty="Пусто" />
        </>
      )}

      {!run && !busy && (
        <Card className="flex flex-col items-center gap-2 py-12 text-center">
          <div className="text-[15px] text-mist">Задай параметры и нажми «Подобрать и сканировать»</div>
          <div className="max-w-md text-[12px] text-ash">
            Скринер подберёт монеты с импульсом объёма (свежий всплеск против обычного) и покажет,
            у кого уже есть сетап. Дефолты — возраст &gt;180д, оборот ≥$5M, импульс ×1.5.
          </div>
        </Card>
      )}
    </div>
  )
}

function fnl(run: ScreenerRun, key: string): string {
  const f = ((run.summary ?? {}) as Record<string, unknown>).funnel as Record<string, unknown> | undefined
  const v = f?.[key]
  return v == null ? '—' : String(v)
}

function FindingsTable({
  title,
  rows,
  gold,
  empty,
}: {
  title: string
  rows: ScreenerFinding[]
  gold?: boolean
  empty: string
}) {
  return (
    <Card className={`p-0 ${gold ? 'border-gold/25' : 'border-line'}`}>
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-[12px] font-semibold uppercase tracking-wide text-mist">{title}</span>
        <span className="text-[11px] text-ash">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-center text-[12px] text-ash">{empty}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[11px] text-ash">
                <th className="px-4 py-2 font-normal">Монета</th>
                <th className="px-4 py-2 font-normal">Импульс</th>
                <th className="px-4 py-2 font-normal">Скор</th>
                <th className="px-4 py-2 font-normal">Сетап</th>
                <th className="px-4 py-2 font-normal">Причина отсева</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.symbol} className="border-t border-line/60">
                  <td className="px-4 py-2 font-semibold text-bone">{f.symbol}</td>
                  <td className="px-4 py-2 tnum">
                    {f.impulse_ratio == null ? '—' : (
                      <span className={f.selected ? 'gild' : 'text-fog'}>×{f.impulse_ratio}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 tnum text-fog">{f.score}</td>
                  <td className="px-4 py-2 text-ash">
                    {f.setups.length === 0
                      ? '—'
                      : f.setups.map((s) => `${s.tf} ${s.status}`).join(', ')}
                  </td>
                  <td className="px-4 py-2 text-ash">{f.reject_reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
