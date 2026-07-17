// Типизированный клиент ядра. Фронт зовёт относительный /api → dev-прокси перенаправляет на ядро.
// Токен оператора (Bearer) — из localStorage; экран входа — Login.tsx + гейт RequireAuth (App.tsx, #36).
// Консоль = ДИСПЛЕЙ: деньги считает ядро, здесь только чтение/показ (#32).
const TOKEN_KEY = 'mfc.operator.token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY)

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

// Вход оператора: POST /v1/auth/login → {token} в localStorage. Пароль вводит Оператор (RBAC ядра).
export async function login(email: string, password: string): Promise<void> {
  const res = await fetch('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    throw new ApiError(res.status, res.status === 401 ? 'Неверный email или пароль' : `Ошибка ${res.status}`)
  }
  const data = (await res.json()) as { token: string }
  setToken(data.token)
}

export const logout = () => setToken(null)

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// ── известные ручки ядра (Ф3) ────────────────────────────────────────────────
// Роллап-агрегаты флота (AUM / P&L / кривая капитала) endpoint'а пока НЕ имеют — считать
// деньги на фронте нельзя (#32); Обзор берёт их из фикстур до бэкенд-подзадачи агрегатов.

export type StuckAccount = {
  account_id: string
  client_id: string
  exchange: string
  label: string | null
  reason: string
  pending_period_start: string
  prev_currency?: string
  contract_currency?: string
}

// Readout застрявшего биллинга (#32, уже в ядре) — питает «Требует внимания» на Обзоре.
export const getStuckAccounts = () =>
  api<{ as_of: string; stuck: StuckAccount[] }>('/v1/billing/stuck-accounts')

// Агрегаты флота (#36) — живой источник Обзора (заменит фикстуры после экрана логина).
export type FleetOverview = {
  as_of: string
  bots: { running: number; paused: number; total: number }
  clients: number
  aum: string
  pnl_net_closed: string
  commission_accrued: string
  open_periods: number
  currency: string
}
export const getFleetOverview = () => api<FleetOverview>('/v1/fleet/overview')

// Живой список клиентов CRM ядра (/v1/clients). v1-форма минимальна: id/имя/активность;
// капитал/комиссия — на договорах (подключим по мере вывода экранов на живые данные).
export type Client = { id: string; name: string; is_active: boolean }
export const getClients = () => api<Client[]>('/v1/clients')

// Живой список инстансов флота (/v1/fleet/instances): бот = инстанс. Профиль/просадка/P&L
// per-instance пока не выведены ядром — показываем что есть (клиент/статус/health/equity).
export type FleetInstance = {
  id: string
  client: string
  status: string
  health: string
  equity: string | null
}
export const getFleetInstances = () => api<FleetInstance[]>('/v1/fleet/instances')

// ── scout-снимки инстанса (ADR-0016, #52 readout) — питает живой экран Разведки (#53) ──────────
// TS-типы = зеркало contracts/telemetry-scout.schema.json. Консоль показывает СНИМОК (не живой тик):
// %-до-входа/свежесть считаем на фронте от полей снимка, честно подписывая scan_ts/data_upto (ADR-0001).
export type ScoutLevelRole = 'A' | 'B' | 'entry_0382' | 'entry_05' | 'entry_0618' | 'stop'
export type ScoutLevel = { role: ScoutLevelRole; price: number }
export type ScoutKline = { time: number; o: number; h: number; l: number; c: number; v: number }
export type ScoutOrder = {
  order_id: string; side: string; type: string; px: number; qty: number; status: string
}
export type ScoutPosition = { side: string; avg_px: number; size: number; live_pnl: number }
export type ScoutConfigMismatch = { flag: boolean; details?: Record<string, unknown> }
export type ScoutSnapshot = {
  symbol: string
  tf: '4h' | '1h'
  state: 'forming' | 'tracking' | 'ready'
  score: number
  bars_since_anchor?: number
  levels?: ScoutLevel[]
  klines_tf?: '4h' | '1h' | '15m' | '5m'
  klines?: ScoutKline[]
  orders?: ScoutOrder[]
  position?: ScoutPosition | null
  scan_ts: string
  orders_ts: string
  data_upto: string
  detector_version: string
  config_fingerprint: string
  config_mismatch: ScoutConfigMismatch
  producer: string
  received_at: string // добавляет readout ядра
}
export const getInstanceScout = (instanceId: string) =>
  api<ScoutSnapshot[]>(`/v1/instances/${instanceId}/scout`)

// ── скринер по параметрам (С7-2б, ядро routes_screener) — питает экран «Скринер» ────────────────
export type ScreenerParams = {
  min_age_days: number
  min_turnover_usd: number
  k: number
  days: number
  universe_max: number
  tfs: string[]
}
export type ScreenerSetup = { tf: string; status: string; score?: number }
export type ScreenerFinding = {
  symbol: string
  impulse_ratio: number | null
  score: number
  selected: boolean
  reject_reason: string | null
  setups: ScreenerSetup[]
}
export type ScreenerRun = {
  run_id: string
  instance_id: string
  status: string // queued | running | done | error
  params: ScreenerParams
  summary: Record<string, unknown> | null
  created_at: string | null
  updated_at: string | null
  findings?: ScreenerFinding[]
}
export const enqueueScreenerRun = (instanceId: string, params: Partial<ScreenerParams>) =>
  api<{ run_id: string; status: string }>(`/v1/instances/${instanceId}/screener/runs`, {
    method: 'POST',
    body: JSON.stringify(params),
  })
export const getScreenerRun = (runId: string) => api<ScreenerRun>(`/v1/screener/runs/${runId}`)
export const listScreenerRuns = (instanceId: string) =>
  api<ScreenerRun[]>(`/v1/instances/${instanceId}/screener/runs`)

// Разведка/Скринер показывают только разведчика (Галахад) и боевого (Персиваль); тестовые
// болванки флота скрыты (директива Куратора, С7 микро-пункт). Фильтр по имени клиента — v1.
const _SCOUT_VISIBLE = /Галахад|Персиваль/
export const visibleScoutInstances = (list: FleetInstance[]) =>
  list.filter((i) => _SCOUT_VISIBLE.test(i.client))

// ── engine_state инстанса (карточка бота, S7) — факт-слой движка для Оператора ──────────────────
export type EnginePosition = {
  symbol: string
  side: string
  avg_px: number
  size: number
  live_pnl: number
}
export type EngineOrder = {
  symbol: string
  order_id: string
  side: string
  type: string
  px: number
  qty: number
  status: string
}
export type EngineTrade = { symbol: string; side: string; qty: number; pnl: number; ts: string }
export type EngineEvent = { kind: string; ts: string; detail: string }
export type EngineState = {
  status: { state: string; kill_switch: boolean; alarm: boolean; stale: boolean; banner: string }
  capital: {
    equity: number
    peak: number
    dd_pct: number
    unrealised_pnl: number
    realised_pnl: number
    open_count: number
  }
  positions: EnginePosition[]
  orders: EngineOrder[]
  trades: EngineTrade[]
  events: EngineEvent[]
}
export type EngineStateResp = {
  instance_id: string
  received_at: string | null
  state: EngineState | null
}
export const getEngineState = (instanceId: string) =>
  api<EngineStateResp>(`/v1/instances/${instanceId}/engine-state`)

// ── Набор Оператора (НАБОР-1, витрина+хранение) — отмеченные звёздочкой сетапы ───────────────────
// Глобальная корзина Оператора; ядро аддитивно, НИЧЕГО не торгует. context — снимок контекста сетапа
// (недоверен, показываем как есть). Ключ дедупа — (symbol, tf): повторная звёздочка upsert'ит контекст.
export type BasketItem = {
  id: string
  symbol: string
  tf: string
  source: 'scout' | 'screener'
  context: Record<string, unknown>
  note: string | null
  created_at: string | null
}
export type BasketAdd = {
  symbol: string
  tf: string
  source: 'scout' | 'screener'
  context?: Record<string, unknown>
  note?: string | null
}
export const getBasket = () => api<BasketItem[]>('/v1/basket/items')
export const addToBasket = (body: BasketAdd) =>
  api<BasketItem>('/v1/basket/items', { method: 'POST', body: JSON.stringify(body) })
export const removeBasketItem = (id: string) =>
  api<void>(`/v1/basket/items/${id}`, { method: 'DELETE' })
// ключ звёздочки «в наборе?» — совпадает с uniq (symbol, tf) ядра
export const basketKey = (symbol: string, tf: string) => `${symbol}|${tf}`
