// Производные экрана Разведки (#53): консоль показывает СНИМОК скаута (не живой тик; ADR-0001).
// Всё считаем от полей снимка, честно подписывая scan_ts/data_upto. Ничего не выдумываем.
import {
  getFleetInstances,
  getInstanceScout,
  type FleetInstance,
  type ScoutLevelRole,
  type ScoutSnapshot,
} from '@/lib/api'

export type BoardColumn = 'forming' | 'tracking' | 'ready' | 'committed'

export const COLUMNS: { key: BoardColumn; label: string }[] = [
  { key: 'forming', label: 'Формируется' },
  { key: 'tracking', label: 'Отслеживаем' },
  { key: 'ready', label: 'Готов' },
  { key: 'committed', label: 'Взят ботом' },
]

// Committed — ПРОИЗВОДНАЯ UI (не state движка): снимок с позицией ИЛИ живыми ордерами = бот взял.
export const isCommitted = (s: ScoutSnapshot): boolean =>
  Boolean(s.position) || (s.orders?.length ?? 0) > 0

export const boardColumn = (s: ScoutSnapshot): BoardColumn =>
  isCommitted(s) ? 'committed' : s.state

export const levelOf = (s: ScoutSnapshot, role: ScoutLevelRole): number | undefined =>
  s.levels?.find((l) => l.role === role)?.price

export const lastClose = (s: ScoutSnapshot): number | undefined =>
  s.klines && s.klines.length ? s.klines[s.klines.length - 1].c : undefined

// %-до-входа: (последний close снимка − верхний вход 0.382)/вход. Производная НА ФРОНТЕ, подпись
// «на закрытие {data_upto}» — живого тика цены в ядре НЕТ (ADR-0001). undefined, если нет данных.
export function pctToEntry(s: ScoutSnapshot): number | undefined {
  const entry = levelOf(s, 'entry_0382')
  const close = lastClose(s)
  if (entry == null || close == null || entry === 0) return undefined
  return ((close - entry) / entry) * 100
}

export const scanAgeMinutes = (s: ScoutSnapshot, now = Date.now()): number =>
  Math.max(0, (now - Date.parse(s.scan_ts)) / 60000)

// Порог устаревания = 2 сигнальных бара ТФ сетапа (4h→480 мин, 1h→120 мин).
export const staleThresholdMin = (tf: ScoutSnapshot['tf']): number => (tf === '1h' ? 120 : 480)

export const isStale = (s: ScoutSnapshot, now = Date.now()): boolean =>
  scanAgeMinutes(s, now) > staleThresholdMin(s.tf)

const STAGE_RANK: Record<BoardColumn, number> = { ready: 0, tracking: 1, forming: 2, committed: 3 }

// Сортировка внутри колонки: стадия → скор (убыв.) → свежесть (новее выше) → монета.
export function sortSnaps(snaps: ScoutSnapshot[]): ScoutSnapshot[] {
  return [...snaps].sort(
    (a, b) =>
      STAGE_RANK[boardColumn(a)] - STAGE_RANK[boardColumn(b)] ||
      b.score - a.score ||
      Date.parse(b.scan_ts) - Date.parse(a.scan_ts) ||
      a.symbol.localeCompare(b.symbol),
  )
}

export type ScoutBoard = {
  instances: FleetInstance[]
  byInstance: Record<string, ScoutSnapshot[]>
  freshest: string | null // инстанс с самыми свежими снимками (дефолт селектора)
}

// Один загрузчик доски: инстансы флота + снимки КАЖДОГО (параллельно) → карта + свежайший.
// Ошибка одного инстанса не роняет доску (тот показывается пустым).
export async function loadScoutBoard(): Promise<ScoutBoard> {
  const instances = await getFleetInstances()
  const scouts = await Promise.all(
    instances.map((i) => getInstanceScout(i.id).catch(() => [] as ScoutSnapshot[])),
  )
  const byInstance: Record<string, ScoutSnapshot[]> = {}
  let freshest: string | null = null
  let freshestTs = -1
  instances.forEach((inst, idx) => {
    const snaps = scouts[idx]
    byInstance[inst.id] = snaps
    const maxTs = snaps.reduce((m, s) => Math.max(m, Date.parse(s.scan_ts) || 0), 0)
    if (snaps.length && maxTs > freshestTs) {
      freshestTs = maxTs
      freshest = inst.id
    }
  })
  return { instances, byInstance, freshest }
}
