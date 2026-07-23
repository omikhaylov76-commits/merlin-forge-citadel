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
// S8 единая Разведка: ПРАВДА ДВИЖКА per-coin — факты warm.classify (та же функция, что решает
// постановку). kind=null — активного сетапа нет; поля НЕТ — правда не посчитана («неизвестно»).
// Русская лексика причин выводится на фронте из фактов (лексики в Контракте нет).
export type ScoutEngine = {
  kind: 'PENDING' | 'OPEN' | null
  auto_eligible: boolean
  reanchored: boolean
  in_universe: boolean // монета в рабочем наборе движка (нет → F-lookahead «мимо списка»)
  side?: string
  age_bars?: number
  entries?: Record<string, number> // {'0.382'/'0.5'/'0.618': цена} — реальная сетка постановки
  stop?: number
  targets?: Record<string, number>
  est_risk_pct?: number | null
}
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
  verified?: boolean // S8/F-scout-snap: levels = РЕАЛЬНАЯ сетка сделки движка (held-символ), не оценка скаута
  engine?: ScoutEngine | null // S8 единая Разведка: правда движка (нет/null = не посчитана)
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

// Разведка/Скринер показывают разведчика (Галахад), боевого (Персиваль) и динамика Борса (S8);
// тестовые болванки флота скрыты (директива Куратора, С7 микро-пункт). Фильтр — v1.
// Борс опознаём по id-префиксу: его инстанс заведён под общим клиентом (GAWAIN), имя «Борс» не матчит.
// Единую Разведку («чьими глазами» для всего флота) обобщим отдельно — этот whitelist временный.
const _SCOUT_VISIBLE = /Галахад|Персиваль|Борс/
const _SCOUT_VISIBLE_IDS = ['cd8d0534'] // Борс-динамик (S8 «Динамо-близнец»)
export const visibleScoutInstances = (list: FleetInstance[]) =>
  list.filter((i) => _SCOUT_VISIBLE.test(i.client) || _SCOUT_VISIBLE_IDS.some((p) => i.id.startsWith(p)))

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
// S8/ADR-0020: стек рабочих монет динамической вселенной (символ+стадия+скор из провайдера)
// S8 per-coin бары: mb1/mb2 = толчковые бары монеты у движка (volnorm/config), bar_source — их
// происхождение. Опциональны (старые снимки/scout-режим их не несут → «—»).
export type EngineStackItem = {
  symbol: string
  stage: string | null
  score: number | null
  tf: string | null
  mb1?: number | null
  mb2?: number | null
  bar_source?: string | null
}
export type EngineStack = { cap: number; count: number; items: EngineStackItem[] }
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
  // ТОЛЬКО у динамик-бота (Борс); фикс-набор/Персиваль — ключа нет (секция «Стек» не рендерится)
  stack?: EngineStack
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

// ── Разведка-стол: настройки дозора (S7, routes_dozor) — питает плашку + рояль ────────────────────
// Ядро = ИСТИНА (Q4): хранит desired-пороги + журнал, доставляет картриджу командой dozor_apply.
// Консоль = дисплей+редактор desired: 7 крутилок группы 1 правит Оператор, экспертные 5 идут как есть.
export type DozorSettings = {
  min_age_days: number
  min_turnover_usd: number
  max_spread_pct: number
  min_history_bars: number
  min_score: number
  universe_max: number
  list_max: number
  tfs: string[]
  primary_tf: string
  fresh_bars: number
  scan_bars: number
  cal_bars: number
  cal_utc_hour: number
  rps: number
}
export type DozorApply = { status: string; at?: string | null }
export type DozorSettingsResp = {
  settings: DozorSettings
  defaults: DozorSettings
  apply: DozorApply
  updated_at: string | null
}
export const getDozorSettings = (instanceId: string) =>
  api<DozorSettingsResp>(`/v1/instances/${instanceId}/scout/settings`)
export const putDozorSettings = (instanceId: string, settings: DozorSettings) =>
  api<{ settings: DozorSettings; apply: DozorApply }>(
    `/v1/instances/${instanceId}/scout/settings`,
    { method: 'PUT', body: JSON.stringify(settings) },
  )
// Кнопка «Сканировать сейчас» — команда scan_now (картридж пишет триггер в scout_control).
export const scanNow = (instanceId: string) =>
  api<{ status: string; command_id: string }>(
    `/v1/instances/${instanceId}/scout/scan-now`,
    { method: 'POST' },
  )
// F-warm-button (ADR-0022): «Поставить» валидный сетап по команде. Оператор-only — портал НЕ видит.
// Команда warm_apply → картридж кладёт WARM_APPLY-интент → движок ставит (maybe_warm→_warm_one_button:
// валидный PENDING, вкл. reanchored; OPEN/has_active/cap→skip; single-shot). Движок сам валидирует.
export const warmApply = (instanceId: string, coins: string[]) =>
  api<{ status: string; command_id: string }>(
    `/v1/instances/${instanceId}/scout/warm-apply`,
    { method: 'POST', body: JSON.stringify({ coins }) },
  )
export type DozorJournalEntry = {
  ts: string | null
  actor: string
  before: Record<string, unknown>
  after: Record<string, unknown>
}
export const getDozorJournal = (instanceId: string) =>
  api<DozorJournalEntry[]>(`/v1/instances/${instanceId}/scout/settings/journal`)

// ── Динамика (S8/ADR-0020, routes_dynamic) — критерии динамической вселенной ──────────────────────
// Ядро = ИСТИНА: хранит desired-критерии (min_score/stack_max/fresh_bars) движко-скоупа. Картридж
// забирает своим /self и применяет ЖИВЬЁМ (провайдер читает файл-критерии, без рестарта; re-fetch ~5мин).
// Команды НЕТ (D2). Дозор-скоуп (капитализация/оборот) — отдельный канал, не смешиваем (ADR-0018 п.3).
export type DynamicSettings = {
  min_score: number
  stack_max: number
  fresh_bars: number
}
export type DynamicSettingsResp = {
  settings: DynamicSettings
  defaults: DynamicSettings
  updated_at: string | null
}
export const getDynamicSettings = (instanceId: string) =>
  api<DynamicSettingsResp>(`/v1/instances/${instanceId}/dynamic/settings`)
export const putDynamicSettings = (instanceId: string, settings: DynamicSettings) =>
  api<{ settings: DynamicSettings }>(
    `/v1/instances/${instanceId}/dynamic/settings`,
    { method: 'PUT', body: JSON.stringify(settings) },
  )
