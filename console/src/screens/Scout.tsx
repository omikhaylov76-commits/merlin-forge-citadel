import { useEffect, useMemo, useState } from 'react'
import { Chip, PageHead, Toolbar } from '@/components/ui/page'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useAsync } from '@/lib/useAsync'
import {
  addToBasket,
  basketKey,
  getBasket,
  getDozorSettings,
  removeBasketItem,
  warmApply,
  type ScoutSnapshot,
  visibleScoutInstances,
} from '@/lib/api'
import {
  loadScoutBoard,
  sortSnaps,
  TRADING_TF,
  VERDICT_COLUMNS,
  verdictColumn,
} from '@/lib/scout'
import { ScoutCard } from './scout/ScoutCard'
import { ScoutDetail } from './scout/ScoutDetail'
import { ProducerLabel, StaleBadge } from './scout/Badges'
import { DozorStrip } from './scout/DozorStrip'
import { DozorPanel } from './scout/DozorPanel'

// ЕДИНАЯ Разведка (S8, подпись Куратора): один экран «чьими глазами смотрим» — селектор бота
// правит всем; доска = 4 колонки ПО ВЕРДИКТУ ДВИЖКА (факты engine из снимка: warm-реплей той же
// функции, что ставит ордера), не по стадии скаута. «Представителя» больше нет. Торговый ТФ
// НАСЛЕДУЕТСЯ от бота (readout, не тумблер). Всё — СНИМОК скаута, не живой тик (дисклеймер).
const SELECTED_KEY = 'mfc.scout.selected' // последний выбранный бот переживает перезагрузку

export function Scout() {
  const board = useAsync(loadScoutBoard, [])
  const [selected, setSelected] = useState<string | null>(
    () => localStorage.getItem(SELECTED_KEY) || null,
  )
  const [minScore, setMinScore] = useState(false)
  const [detail, setDetail] = useState<ScoutSnapshot | null>(null)
  const [panelOpen, setPanelOpen] = useState(false) // рояль настроек дозора
  // «Поставить» на карточке (колонка «нужна кнопка», ADR-0022): per-монета idle→busy→sent(⏳);
  // sent держим до ~16 мин (ближайший 15m-тик исполнит; движок сам валидирует).
  const [warmSent, setWarmSent] = useState<Record<string, 'busy' | 'sent'>>({})
  const dozor = useAsync(
    () => (selected ? getDozorSettings(selected) : Promise.resolve(null)),
    [selected],
  )
  const basket = useAsync(getBasket, [])
  const [starBusy, setStarBusy] = useState<string | null>(null)
  const inBasket = useMemo(() => {
    const m = new Map<string, string>()
    for (const b of basket.data ?? []) m.set(basketKey(b.symbol, b.tf), b.id)
    return m
  }, [basket.data])
  const toggleStar = async (s: ScoutSnapshot) => {
    const key = basketKey(s.symbol, s.tf)
    setStarBusy(key)
    try {
      const existing = inBasket.get(key)
      if (existing) {
        await removeBasketItem(existing)
      } else {
        await addToBasket({
          symbol: s.symbol,
          tf: s.tf,
          source: 'scout',
          context: { score: s.score, stage: s.state, verdict: verdictColumn(s) },
        })
      }
      basket.reload()
    } finally {
      setStarBusy(null)
    }
  }

  const doWarm = async (s: ScoutSnapshot) => {
    if (!selected || warmSent[s.symbol]) return
    setWarmSent((m) => ({ ...m, [s.symbol]: 'busy' }))
    try {
      await warmApply(selected, [s.symbol])
      setWarmSent((m) => ({ ...m, [s.symbol]: 'sent' }))
      window.setTimeout(() => {
        setWarmSent((m) => {
          const rest = { ...m }
          delete rest[s.symbol]
          return rest
        })
      }, 16 * 60_000) // тик прошёл: годный уже «в работе», негодный движок пропустил
    } catch {
      setWarmSent((m) => {
        const rest = { ...m }
        delete rest[s.symbol]
        return rest
      })
    }
  }

  // Выбранный бот: последний сохранённый, иначе первый видимый. Сброс — если исчез из флота.
  useEffect(() => {
    if (!board.data) return
    const ids = visibleScoutInstances(board.data.instances).map((i) => i.id)
    if (selected == null || !ids.includes(selected)) {
      setSelected(ids[0] ?? null)
    }
  }, [board.data, selected])
  useEffect(() => {
    if (selected) localStorage.setItem(SELECTED_KEY, selected)
  }, [selected])

  const instances = board.data ? visibleScoutInstances(board.data.instances) : []
  const selInst = instances.find((i) => i.id === selected)
  const byInstance = board.data?.byInstance ?? {}
  const hasAnyData = Object.values(byInstance).some((s) => s.length > 0)
  const snaps = selected ? (byInstance[selected] ?? []) : []
  // Доска — ТОЛЬКО торговый ТФ бота (наследуется, тумблера нет). Прочие ТФ — свёрнутый хвост.
  const tfSnaps = snaps.filter((s) => s.tf === TRADING_TF)
  const otherTfCount = snaps.length - tfSnaps.length
  const producer = tfSnaps[0]?.producer ?? snaps[0]?.producer ?? '—'
  const freshest = tfSnaps.reduce<ScoutSnapshot | null>(
    (a, s) => (!a || Date.parse(s.scan_ts) > Date.parse(a.scan_ts) ? s : a),
    null,
  )
  // свежесть скана для плашки дозора — время ПРИЁМА свежайшего пуша ядром (received_at)
  const scanTs = snaps.reduce<string | undefined>(
    (a, s) => {
      const t = s.received_at || s.scan_ts
      return !a || Date.parse(t) > Date.parse(a) ? t : a
    },
    undefined,
  )

  const byCol = useMemo(() => {
    let list = tfSnaps
    if (minScore) list = list.filter((s) => s.score >= 35)
    const m: Record<string, ScoutSnapshot[]> = { in_work: [], auto: [], button: [], skip: [] }
    for (const s of sortSnaps(list)) m[verdictColumn(s)].push(s)
    return m
  }, [tfSnaps, minScore])

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
              : `радар и вердикт движка · глазами одного бота · ботов: ${instances.length}`
        }
        action={
          instances.length > 0 ? (
            <label className="flex items-center gap-2 text-[12px] text-fog">
              смотрим глазами
              <select
                value={selected ?? ''}
                onChange={(e) => {
                  setSelected(e.target.value)
                  setDetail(null)
                  setPanelOpen(false)
                }}
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

      {selected && dozor.data && (
        <>
          <DozorStrip
            instanceId={selected}
            settings={dozor.data.settings}
            apply={dozor.data.apply}
            scanTs={scanTs}
            naborCount={basket.data?.length ?? 0}
            open={panelOpen}
            onToggle={() => setPanelOpen((v) => !v)}
            onScanned={board.reload}
          />
          <DozorPanel
            instanceId={selected}
            botName={selInst?.client ?? '—'}
            live={dozor.data.settings}
            open={panelOpen}
            onApplied={dozor.reload}
          />
        </>
      )}

      <Toolbar>
        <span
          className="self-center rounded-pill border border-line px-2.5 py-1 text-[11px] text-ash"
          title="торговый ТФ — свойство бота (SIGNAL_TF генома), Разведка его наследует; выбор ТФ появится в Конструкторе (Ф5)"
        >
          торговый ТФ {TRADING_TF} · от бота
        </span>
        {otherTfCount > 0 && (
          <span
            className="self-center text-[11px] text-steel"
            title="находки скаута на не-торговом ТФ: движок такие не торгует, доска их не показывает"
          >
            + {otherTfCount} на не-торговом ТФ
          </span>
        )}
        <span className="mx-1 self-center text-ash">·</span>
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
      ) : !hasAnyData ? (
        <EmptyState kind="silent" />
      ) : tfSnaps.length === 0 ? (
        <EmptyState kind="quiet" />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {VERDICT_COLUMNS.map((col) => (
              <div
                key={col.key}
                className={`rounded-card border bg-card p-3 ${
                  col.key === 'auto'
                    ? 'border-gold/25'
                    : col.key === 'button'
                      ? 'border-copper/25'
                      : 'border-line'
                }`}
              >
                <div className="mb-3 flex items-center justify-between px-1">
                  <span
                    className="text-[12px] font-semibold uppercase tracking-wide text-mist"
                    title={col.hint}
                  >
                    {col.label}
                  </span>
                  <span className="text-[11px] text-ash">{byCol[col.key].length}</span>
                </div>
                <div className="flex flex-col gap-2">
                  {byCol[col.key].map((s) => (
                    <ScoutCard
                      key={s.symbol + s.tf}
                      snap={s}
                      onOpen={() => setDetail(s)}
                      starred={inBasket.has(basketKey(s.symbol, s.tf))}
                      starBusy={starBusy === basketKey(s.symbol, s.tf)}
                      onStar={() => toggleStar(s)}
                      warmState={warmSent[s.symbol] ?? 'idle'}
                      onWarm={() => doWarm(s)}
                    />
                  ))}
                  {byCol[col.key].length === 0 && (
                    <div className="px-1 py-2 text-[11px] text-ash">пусто</div>
                  )}
                </div>
              </div>
            ))}
          </div>
          {/* дисклеймер подписи Куратора: вердикт считан по снимку скаута, не по живому тику */}
          <p className="mt-3 px-1 text-[11px] leading-snug text-ash">
            Вердикт движка считается по СНИМКУ скаута (свечи его кэша), не по живому тику: на
            границе бара может кратко разойтись с постановкой. Постановка ордеров идёт по свечам
            самого движка — «Поставить»/самоход всегда перепроверяют сетап на 15m-тике.
          </p>
        </>
      )}

      {detail && (
        <ScoutDetail snap={detail} onClose={() => setDetail(null)} onBasketChange={basket.reload} />
      )}
    </div>
  )
}

function SkeletonBoard() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {VERDICT_COLUMNS.map((c) => (
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

// Пустые состояния (#53): ошибка связи / скаут молчит / рынок тихий.
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
        Скаут этого бота на связи, но сейчас подходящих сетапов на торговом ТФ не нашёл. Это
        норма — сетапы бывают не каждый бар.
      </div>
    </Card>
  )
}
