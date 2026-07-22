// Производные экрана Разведки: консоль показывает СНИМОК скаута (не живой тик; ADR-0001).
// S8 единая Разведка: доска — ПО ВЕРДИКТУ ДВИЖКА (факты поля engine = warm.classify, та же
// функция, что решает постановку), не по стадии скаута. Русская лексика причин — ЗДЕСЬ,
// из фактов (Контракт лексики не несёт). Ничего не выдумываем.
import {
  getFleetInstances,
  getInstanceScout,
  type FleetInstance,
  type ScoutLevelRole,
  type ScoutSnapshot,
} from '@/lib/api'

// Торговый ТФ бота: НАСЛЕДУЕТСЯ от бота, не тумблер Разведки (подпись Куратора: гвоздь «4h»
// до Кузницы/Ф5 — SIGNAL_TF захардкожен в геноме, 1h-бот = другой бот). Показ, не выбор.
export const TRADING_TF = '4h' as const

export type VerdictColumn = 'in_work' | 'auto' | 'button' | 'skip'

export const VERDICT_COLUMNS: { key: VerdictColumn; label: string; hint: string }[] = [
  { key: 'in_work', label: 'В работе', hint: 'движок ведёт: живая позиция или ордера' },
  {
    key: 'auto',
    label: 'Готов · движок ставит',
    hint: 'валидный нетронутый сетап — самоход/горн поставит сам',
  },
  {
    key: 'button',
    label: 'Нужна кнопка',
    hint: 'сетка сдвигалась (пере-якорь) — ставится только вручную («Поставить»)',
  },
  { key: 'skip', label: 'Движок не берёт', hint: 'вердикт движка с причиной и судьбой' },
]

// «Взят ботом» — производная факт-слоя (позиция ИЛИ живые ордера в снимке).
export const isCommitted = (s: ScoutSnapshot): boolean =>
  Boolean(s.position) || (s.orders?.length ?? 0) > 0

// Колонка вердикта из ФАКТОВ движка. Порядок важен: факт денег (в работе) старше классификации;
// вне рабочего набора движка сетап не возьмут ни самоход, ни кнопка (maybe_warm фильтрует по
// вселенной) → «мимо списка» в skip, какой бы годный он ни был.
export function verdictColumn(s: ScoutSnapshot): VerdictColumn {
  if (isCommitted(s)) return 'in_work'
  const e = s.engine
  if (!e) return 'skip' // правда не посчитана — честно в «не берёт» с меткой «нет вердикта»
  if (e.kind === 'PENDING' && e.in_universe) return e.auto_eligible ? 'auto' : 'button'
  return 'skip'
}

// Причина + судьба для колонки «Движок не берёт» (и метка «нет вердикта»). Только из фактов:
// kind=null + forming → пробоя ещё нет; kind=null + уровни были → реплей закрыл; годный вне
// набора → F-lookahead; OPEN → вход по рынку ушёл (движок вдогонку не заходит).
export function skipReason(s: ScoutSnapshot): { label: string; fate: string } | null {
  if (verdictColumn(s) !== 'skip') return null
  const e = s.engine
  if (!e) {
    return {
      label: 'нет вердикта',
      fate: 'движок ещё не дал правду по этой монете — ждём свежий снимок',
    }
  }
  const outOfList = {
    label: 'мимо списка',
    fate: 'не в рабочем наборе движка — не возьмёт, даже годный (F-lookahead)',
  }
  if (e.kind === 'OPEN') {
    return e.in_universe
      ? {
          label: 'вход по рынку ушёл',
          fate: 'цена уже в сетке — движок вдогонку не заходит; кнопка такой не ставит',
        }
      : outOfList
  }
  if (e.kind === 'PENDING') {
    return outOfList // в наборе он ушёл бы в auto/button — здесь только вне набора
  }
  // kind=null — активного сетапа у движка нет
  if (s.state === 'forming') {
    return { label: 'созревает', fate: 'пробоя ещё нет — самоход подхватит, когда сетап созреет' }
  }
  return { label: 'отработан', fate: 'реплей движка закрыл сделку (стоп/цель) — сетап мёртв' }
}

export const levelOf = (s: ScoutSnapshot, role: ScoutLevelRole): number | undefined =>
  s.levels?.find((l) => l.role === role)?.price

export const lastClose = (s: ScoutSnapshot): number | undefined =>
  s.klines && s.klines.length ? s.klines[s.klines.length - 1].c : undefined

// Уровень входа с приоритетом ПРАВДЫ ДВИЖКА: сетка engine.entries (реальная постановка), при её
// отсутствии — оценка скаута из levels. Честно: карточка = реальность движка, не зеркало радара.
export function entryOf(s: ScoutSnapshot, key: '0.382' | '0.5' | '0.618'): number | undefined {
  const fromEngine = s.engine?.entries?.[key]
  if (fromEngine != null && fromEngine > 0) return fromEngine
  const role = key === '0.382' ? 'entry_0382' : key === '0.5' ? 'entry_05' : 'entry_0618'
  return levelOf(s, role)
}

export const stopOf = (s: ScoutSnapshot): number | undefined =>
  (s.engine?.stop && s.engine.stop > 0 ? s.engine.stop : undefined) ?? levelOf(s, 'stop')

// Уровни для деталь-графика: входы/стоп ЗАМЕНЕНЫ сеткой движка, когда правда есть (карточка и
// график обязаны показывать одни цифры). A/B скаута остаются — рамка импульса, движок их не несёт.
export function mergeEngineLevels(s: ScoutSnapshot): { role: ScoutLevelRole; price: number }[] {
  const base = s.levels ?? []
  const e = s.engine
  if (!e?.entries) return base
  const grid: Partial<Record<ScoutLevelRole, number | undefined>> = {
    entry_0382: e.entries['0.382'],
    entry_05: e.entries['0.5'],
    entry_0618: e.entries['0.618'],
    stop: e.stop,
  }
  const out = base.map((l) => {
    const p = grid[l.role]
    delete grid[l.role]
    return p != null && p > 0 ? { ...l, price: p } : l
  })
  for (const [role, p] of Object.entries(grid) as [ScoutLevelRole, number | undefined][]) {
    if (p != null && p > 0) out.push({ role, price: p }) // уровень, которого у скаута не было
  }
  return out
}

export const hasEngineGrid = (s: ScoutSnapshot): boolean => Boolean(s.engine?.entries)

// %-до-входа: (последний close снимка − верхний вход)/вход. Производная НА ФРОНТЕ, подпись
// «на закрытие {data_upto}» — живого тика цены в ядре НЕТ (ADR-0001). undefined, если нет данных.
export function pctToEntry(s: ScoutSnapshot): number | undefined {
  const entry = entryOf(s, '0.382')
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

const VERDICT_RANK: Record<VerdictColumn, number> = { in_work: 0, auto: 1, button: 2, skip: 3 }

// Сортировка внутри колонки: вердикт → скор (убыв.) → свежесть (новее выше) → монета.
export function sortSnaps(snaps: ScoutSnapshot[]): ScoutSnapshot[] {
  return [...snaps].sort(
    (a, b) =>
      VERDICT_RANK[verdictColumn(a)] - VERDICT_RANK[verdictColumn(b)] ||
      b.score - a.score ||
      Date.parse(b.scan_ts) - Date.parse(a.scan_ts) ||
      a.symbol.localeCompare(b.symbol),
  )
}

export type ScoutBoard = {
  instances: FleetInstance[]
  byInstance: Record<string, ScoutSnapshot[]>
}

// Один загрузчик доски: инстансы флота + снимки КАЖДОГО (параллельно) → карта per-инстанс.
// «Представителя»/свежайшего НЕТ (подпись Куратора: конец двоякости — выбранный бот правит всем).
// Ошибка одного инстанса не роняет доску (тот показывается пустым).
export async function loadScoutBoard(): Promise<ScoutBoard> {
  const instances = await getFleetInstances()
  const scouts = await Promise.all(
    instances.map((i) => getInstanceScout(i.id).catch(() => [] as ScoutSnapshot[])),
  )
  const byInstance: Record<string, ScoutSnapshot[]> = {}
  instances.forEach((inst, idx) => {
    byInstance[inst.id] = scouts[idx]
  })
  return { instances, byInstance }
}
