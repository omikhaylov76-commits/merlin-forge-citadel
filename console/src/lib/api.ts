// Типизированный клиент ядра. Фронт зовёт относительный /api → dev-прокси перенаправляет на ядро.
// Токен оператора (Bearer) — из localStorage; экран логина/ввода — отдельной подзадачей Ф4.
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
