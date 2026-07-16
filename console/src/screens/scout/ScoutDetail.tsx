import { useEffect, useRef, useState } from 'react'
import { ColorType, createChart, LineStyle, type UTCTimestamp } from 'lightweight-charts'
import { type ScoutSnapshot } from '@/lib/api'
import { Disclaimer, MismatchBadge, StaleBadge } from './Badges'

const fmtP = (n?: number) => (n == null ? '—' : n.toLocaleString('ru-RU', { maximumFractionDigits: 6 }))
const css = (n: string) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888'

const LEVEL_TITLE: Record<string, string> = {
  A: 'A низ',
  B: 'B верх',
  entry_0382: 'вх 0.382',
  entry_05: 'вх 0.5',
  entry_0618: 'вх 0.618',
  stop: 'стоп',
}

// #56: стиль линии уровня по роли (var-имя цвета + LineStyle). Рамка импульса A/B — белый пунктир;
// стоп — красный пунктир; три входа — приглушённые жёлт/зел/сирень точками. Факт-слой (orders/pos) — отдельно.
const LEVEL_STYLE: Record<string, { color: string; style: LineStyle }> = {
  A: { color: '--color-bone', style: LineStyle.Dashed },
  B: { color: '--color-bone', style: LineStyle.Dashed },
  stop: { color: '--color-danger', style: LineStyle.Dashed },
  entry_0382: { color: '--color-gold', style: LineStyle.Dotted },
  entry_05: { color: '--color-ok', style: LineStyle.Dotted },
  entry_0618: { color: '--color-lilac', style: LineStyle.Dotted },
}

// Деталь-вью сетапа: график Lightweight Charts (свечи снимка + слой «теория» разведки vs «факт» бота).
export function ScoutDetail({ snap, onClose }: { snap: ScoutSnapshot; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false) // локально (без localStorage — запрещён в консоли)

  useEffect(() => {
    const el = ref.current
    if (!el || !snap.klines?.length) return
    const fact = css('--color-silver')
    const danger = css('--color-danger')
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: css('--color-ash') },
      grid: { vertLines: { color: css('--color-line') }, horzLines: { color: css('--color-line') } },
      // С7-1: rightOffset — воздух справа (директива). Держится при авто-скролле/fitContent;
      // сам по себе НЕ перебивает явный setVisibleLogicalRange ниже — потому AIR продублирован в правую границу.
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: css('--color-line'), rightOffset: 13 },
      rightPriceScale: { borderColor: css('--color-line') },
    })
    const candles = chart.addCandlestickSeries({
      upColor: css('--color-ok'),
      downColor: danger,
      borderVisible: false,
      wickUpColor: css('--color-ok'),
      wickDownColor: danger,
    })
    // LWC требует СТРОГО возрастающее уникальное time — сортируем+дедупим (защита от несорт. продюсера)
    const rows = [...snap.klines]
      .sort((a, b) => a.time - b.time)
      .filter((k, i, arr) => i === 0 || k.time !== arr[i - 1].time)
    candles.setData(
      rows.map((k) => ({
        time: Math.floor(k.time / 1000) as UTCTimestamp,
        open: k.o,
        high: k.h,
        low: k.l,
        close: k.c,
      })),
    )
    for (const lv of snap.levels ?? []) {
      const st = LEVEL_STYLE[lv.role] ?? { color: '--color-copper', style: LineStyle.Solid }
      candles.createPriceLine({
        price: lv.price,
        color: css(st.color),
        lineWidth: 1,
        lineStyle: st.style,
        axisLabelVisible: true,
        title: LEVEL_TITLE[lv.role] ?? lv.role,
      })
    }
    for (const o of snap.orders ?? []) {
      candles.createPriceLine({
        price: o.px,
        color: fact,
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: true,
        title: `ордер ${o.side}`,
      })
    }
    if (snap.position) {
      candles.createPriceLine({
        price: snap.position.avg_px,
        color: fact,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: `поз ${snap.position.side}`,
      })
    }
    // #56: показываем последние ~80 баров (окно), остальное за кадром — Оператор сам зумит/листает.
    // С7-1: AIR пустых баров справа (воздух между последним баром и шкалой) — правую границу тянем ЗА
    // последний индекс, LWC рисует whitespace. Явный диапазон перекрыл бы опцию rightOffset, потому AIR тут.
    const N = 80
    const AIR = 13
    const n = rows.length
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - N), to: n - 1 + AIR })
    // защита от растяжения ТОЛЬКО для БЕДНОГО снимка (<15 баров): при нём окно = весь ряд, бары
    // раздулись бы во весь экран. На плотном ряде НЕ капим (кап 14 зря сжимал бы). Порог баров — не зума.
    const scale = chart.timeScale()
    if (rows.length < 15 && scale.options().barSpacing > 14) {
      scale.applyOptions({ barSpacing: 14 })
    }
    return () => chart.remove()
    // expanded в deps: при развороте пере-создаём график в новом (большем) контейнере →
    // autoSize + fitContent + barSpacing-кап отрабатывают на новом размере (директива).
  }, [snap, expanded])

  const lv = (r: string) => snap.levels?.find((l) => l.role === r)?.price
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-void/70 p-4"
      onClick={onClose}
    >
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-card border border-line bg-floating p-5 ${
          expanded ? 'max-w-[1560px]' : 'max-w-[1080px]'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-serif text-[22px] text-bone">{snap.symbol}</h2>
              <span className="rounded-pill border border-line px-2 text-[11px] text-ash">
                {snap.state} · {snap.tf} · скор {Math.round(snap.score)}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <StaleBadge snap={snap} />
              <MismatchBadge snap={snap} />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setExpanded((v) => !v)}
              className="rounded-pill border border-line px-3 py-1 text-[13px] text-fog hover:text-mist"
            >
              {expanded ? '⤡ свернуть' : '⤢ развернуть'}
            </button>
            <button
              onClick={onClose}
              className="rounded-pill border border-line px-3 py-1 text-[13px] text-fog hover:text-mist"
            >
              ✕ закрыть
            </button>
          </div>
        </div>

        <div className="mb-2 flex flex-wrap items-center gap-4 text-[11px]">
          <span className="flex items-center gap-1.5 text-copper">
            <i className="inline-block h-1.5 w-4 rounded bg-copper" /> Разведка (теория)
          </span>
          <span className="flex items-center gap-1.5 text-silver">
            <i className="inline-block h-1.5 w-4 rounded bg-silver" /> Ордера бота (факт)
          </span>
          {snap.klines_tf && <span className="text-ash">свечи: {snap.klines_tf}</span>}
        </div>

        {snap.klines?.length ? (
          <div
            ref={ref}
            className={`w-full rounded-card border border-line bg-card ${
              expanded ? 'h-[600px]' : 'h-[360px]'
            }`}
          />
        ) : (
          <div className="flex h-[200px] items-center justify-center rounded-card border border-line bg-card text-[13px] text-ash">
            Свечей в снимке нет (скаут Фазы 1) — уровни ниже.
          </div>
        )}

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-card border border-line bg-card p-3 text-[12px]">
            <div className="mb-2 text-mist">Как собран сетап</div>
            <dl className="grid grid-cols-2 gap-y-1 text-ash tnum">
              <dt>A (низ импульса)</dt>
              <dd className="text-right text-fog">{fmtP(lv('A'))}</dd>
              <dt>B (вершина)</dt>
              <dd className="text-right text-fog">{fmtP(lv('B'))}</dd>
              <dt>входы 0.382/0.5/0.618</dt>
              <dd className="text-right text-fog">
                {fmtP(lv('entry_0382'))} / {fmtP(lv('entry_05'))} / {fmtP(lv('entry_0618'))}
              </dd>
              <dt>стоп</dt>
              <dd className="text-right text-danger">{fmtP(lv('stop'))}</dd>
              <dt>скор</dt>
              <dd className="text-right text-fog">{Math.round(snap.score)}</dd>
            </dl>
          </div>
          <div className="rounded-card border border-line bg-card p-3 text-[12px]">
            <div className="mb-2 text-mist">Факт (движок)</div>
            {snap.orders?.length || snap.position ? (
              <div className="space-y-1 text-ash tnum">
                {snap.position && (
                  <div>
                    позиция {snap.position.side} · вход {fmtP(snap.position.avg_px)} · размер{' '}
                    {snap.position.size} · PnL {snap.position.live_pnl}
                  </div>
                )}
                {(snap.orders ?? []).map((o) => (
                  <div key={o.order_id}>
                    ордер {o.side} {o.type} @ {fmtP(o.px)} · {o.qty} · {o.status}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-ash">Боевых ордеров/позиции нет (dry-run / сетап не взят).</div>
            )}
            <div className="mt-2 text-[11px] text-ash">
              detector: {snap.detector_version} · fp: {snap.config_fingerprint.slice(0, 18)}
            </div>
          </div>
        </div>

        <div className="mt-3">
          <Disclaimer />
        </div>
      </div>
    </div>
  )
}
