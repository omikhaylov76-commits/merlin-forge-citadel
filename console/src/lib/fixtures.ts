// ФИКСТУРЫ Обзора (демо-данные дисплея). Роллап-агрегаты флота (AUM / P&L / кривая капитала /
// лента) endpoint'ов ядра пока не имеют — считать деньги на фронте нельзя (#32).
// TODO(Ф4-backend): агрегат-эндпоинты флота → заменить фикстуры живыми данными.
export const overviewFixture = {
  aum: 248610,
  aumDeltaPct: 4.2,
  pnlNet: 11900,
  botsRunning: 17,
  botsTotal: 19,
  botsPaused: 2,
  toBill: 1786,
  periodsToClose: 3,
  capitalDelta30d: 9940,
  drawdownFromPeak: 3.1,
  // кривая капитала: нормализованные точки высоты 0..1 (для SVG-полилинии)
  equityCurve: [0.1, 0.18, 0.15, 0.32, 0.28, 0.3, 0.48, 0.44, 0.66, 0.62, 0.8, 0.92],
  attention: [
    { kind: 'k', who: 'bot-014 · Клиент-07', what: 'Kill-switch · −51%', tag: 'разобрать' },
    { kind: 'a', who: 'bot-006 · Клиент-03', what: 'Просадка у порога', tag: '−38%' },
    { kind: 'a', who: 'Клиент-11', what: 'Ключ протухает 3 дня', tag: 'ключ' },
    { kind: 'p', who: 'bot-009', what: 'Heartbeat молчит 12 мин', tag: 'проверить' },
    { kind: 'p', who: 'Клиент-05', what: 'Период к закрытию', tag: '$612' },
  ] as { kind: 'k' | 'a' | 'p'; who: string; what: string; tag: string }[],
  health: { worst: 'bot-014', current: 51, alarm: 40, stop: 50, median: 22 },
  feed: [
    { t: '09:14', kind: 'kill', text: 'bot-014 остановлен' },
    { t: '08:47', kind: 'bill', text: 'Клиент-05 готов к счёту' },
    { t: '07:32', kind: 'alarm', text: 'bot-006 −38%' },
    { t: '02:55', kind: 'ok', text: 'Кавалл: облако и БД в норме' },
  ] as { t: string; kind: 'kill' | 'bill' | 'alarm' | 'ok'; text: string }[],
}

export type OverviewData = typeof overviewFixture

// ── Флот (демо; живой источник — список инстансов ядра, TODO Ф4-backend) ───────
export type BotStatus = 'live' | 'pause' | 'alarm' | 'kill'
export const fleetFixture: {
  bot: string
  client: string
  profile: string
  dd: number
  hb: 'ok' | 'dead'
  pnl: number | null
  status: BotStatus
}[] = [
  { bot: 'bot-002', client: 'Клиент-01', profile: 'Консерватор-10', dd: 22, hb: 'ok', pnl: 1240, status: 'live' },
  { bot: 'bot-006', client: 'Клиент-03', profile: 'Агрессор v3', dd: 76, hb: 'ok', pnl: -310, status: 'alarm' },
  { bot: 'bot-009', client: 'Клиент-02', profile: 'Консерватор-10', dd: 31, hb: 'dead', pnl: null, status: 'pause' },
  { bot: 'bot-014', client: 'Клиент-07', profile: 'Агрессор v3', dd: 100, hb: 'ok', pnl: -2050, status: 'kill' },
  { bot: 'bot-021', client: 'Клиент-11', profile: 'Скальпер', dd: 18, hb: 'ok', pnl: 640, status: 'live' },
]

// ── Сделки (демо; живой источник — журнал trades ядра, TODO Ф4-backend) ────────
export const dealsFixture: {
  t: string
  bot: string
  pair: string
  side: string
  leg: string
  price: string
  pnl: number
}[] = [
  { t: '09:12', bot: 'bot-002', pair: 'ETHUSDT', side: 'Long', leg: '0.5', price: '1 834.20', pnl: 180 },
  { t: '08:40', bot: 'bot-021', pair: 'SOLUSDT', side: 'Long', leg: '0.382', price: '168.44', pnl: 92 },
  { t: '08:05', bot: 'bot-006', pair: 'INJUSDT', side: 'Long', leg: '0.618', price: '21.07', pnl: -44 },
  { t: '07:22', bot: 'bot-002', pair: 'BTCUSDT', side: 'Long', leg: '0.5', price: '64 210', pnl: 310 },
]

// ── Клиенты (демо; живой источник — CRM-API ядра /v1 clients, TODO Ф4-backend) ─
export type ClientRow = {
  name: string
  fav: boolean
  capital: number
  net: number
  hwm: number
  gild: boolean
  sub: string
  meta: string[]
  toBill: number
  note: string
  exchange: string
  contractStatus: string
}
export const clientsFixture: ClientRow[] = [
  { name: 'Клиент-01', fav: true, capital: 42100, net: 3100, hwm: 39000, gild: true, sub: 'net +$3.1K · HWM $39K', meta: ['2 бота', '3 сделки', 'DD 22%'], toBill: 465, note: '7 дн до закрытия', exchange: 'Bybit', contractStatus: 'подписан' },
  { name: 'Клиент-11', fav: true, capital: 61400, net: 5400, hwm: 56000, gild: true, sub: 'net +$5.4K · HWM $56K', meta: ['1 бот', '1 сделка', 'DD 18%'], toBill: 812, note: 'ключ ⚠ 3 дня', exchange: 'Bybit', contractStatus: 'подписан' },
  { name: 'Клиент-03', fav: false, capital: 28300, net: -300, hwm: 30000, gild: false, sub: 'net −$0.3K · HWM $30K', meta: ['1 бот', '2 сделки', 'DD 38%'], toBill: 0, note: 'под HWM', exchange: 'Bybit', contractStatus: 'подписан' },
  { name: 'Клиент-07', fav: false, capital: 18050, net: -2000, hwm: 20050, gild: false, sub: 'net −$2.0K · стоп сработал', meta: ['1 бот', 'стоп', 'DD 51%'], toBill: 0, note: 'разобрать', exchange: 'Bybit', contractStatus: 'подписан' },
  { name: 'Клиент-02', fav: false, capital: 15900, net: 0, hwm: 16000, gild: false, sub: 'пауза · HWM $16K', meta: ['1 бот', 'пауза'], toBill: 0, note: '—', exchange: 'Bybit', contractStatus: 'подписан' },
]

// ── Разведка (скаут, kanban; демо — живой источник = scout-сервис) ─────────────
export type ScoutCand = { pair: string; score: number | string; m1: string; m2: string; committed?: boolean }
export const scoutFixture: { column: string; count: number; ready?: boolean; cands: ScoutCand[] }[] = [
  {
    column: 'Forming',
    count: 12,
    cands: [
      { pair: 'WIFUSDT', score: 41, m1: '0.382 / 0.5', m2: '7 баров' },
      { pair: 'TIAUSDT', score: 38, m1: 'формируется', m2: '3 бара' },
    ],
  },
  { column: 'Tracking', count: 5, cands: [{ pair: 'SOLUSDT', score: 62, m1: 'вход 0.5', m2: '% до 1.2%' }] },
  {
    column: 'Ready',
    count: 3,
    ready: true,
    cands: [
      { pair: 'ETHUSDT', score: 78, m1: 'вход 0.5 · стоп fib1', m2: '% до 0.3%' },
      { pair: 'INJUSDT', score: 71, m1: 'вход 0.382', m2: '% до 0.6%' },
    ],
  },
  { column: 'Committed', count: 2, cands: [{ pair: 'BTCUSDT', score: 'взят', m1: 'bot-002 →', m2: '+$310', committed: true }] },
]

// ── Профили (библиотека рецептов; демо) ────────────────────────────────────────
export const profilesFixture: {
  name: string
  status: 'допущен' | 'demo'
  track: string
  calmar: string
  dd: string
  deploys: number
  oos: string
  fav?: boolean
}[] = [
  { name: 'Консерватор-10', status: 'допущен', track: 'живой трек 8 нед', calmar: '2.0', dd: '−24%', deploys: 4, oos: 'OOS ✓ 02.07', fav: true },
  { name: 'Агрессор v3', status: 'demo', track: 'бэктест', calmar: '3.5', dd: '−34%', deploys: 2, oos: 'не обкатан' },
  { name: 'Скальпер', status: 'допущен', track: 'живой трек 4 нед', calmar: '1.9', dd: '−19%', deploys: 1, oos: 'OOS ✓' },
]

// ── Отчёты (архив документов; демо) ────────────────────────────────────────────
export const reportsFixture: { doc: string; type: string; client: string; period: string; status: string }[] = [
  { doc: 'Расчёт HWM · июнь', type: 'HWM-счёт', client: 'Клиент-01', period: '2026-06', status: 'отправлен' },
  { doc: 'Выписка · июнь', type: 'Выписка', client: 'Клиент-11', period: '2026-06', status: 'скачан' },
  { doc: 'Налоговая сводка', type: 'Налоговый', client: '—', period: '2026-06', status: 'сформирован' },
]

// ── Тревоги (две семьи: Торговые + Системные; демо) ─────────────────────────────
export type AlertSev = 'KILL' | 'ALARM' | 'КЛЮЧ' | 'HEARTBEAT' | 'БИЛЛИНГ' | 'СИСТЕМА'
export const alertsFixture: {
  sev: AlertSev
  family: 'Торговые' | 'Системные'
  title: string
  detail: string
  action: string
  resolved: boolean
}[] = [
  { sev: 'KILL', family: 'Торговые', title: 'bot-014 · Клиент-07 — сработал аварийный стоп', detail: 'Просадка −51% превысила порог −50%. Позиции закрыты, бот остановлен.', action: 'разобрать', resolved: false },
  { sev: 'ALARM', family: 'Торговые', title: 'bot-006 · Клиент-03 — просадка у порога', detail: '−38%, приближается к тревоге −40%.', action: 'к боту', resolved: false },
  { sev: 'КЛЮЧ', family: 'Торговые', title: 'Клиент-11 — API-ключ истекает через 3 дня', detail: 'Продлить или заменить ключ, иначе бот встанет.', action: 'сменить', resolved: false },
  { sev: 'СИСТЕМА', family: 'Системные', title: 'Кавалл: скаут-сервис отвечал с задержкой', detail: 'pifagor-scout лаг 8с в 08:30, восстановился. Троттлинг REST. Действий не требуется.', action: 'лог', resolved: true },
]

// Деталь карточки клиента (демо, представительная — по макету s-client).
export const clientDetailFixture = {
  bots: [{ bot: 'bot-021', profile: 'Скальпер', dd: 18, pnl: 640, status: 'live' as const }],
  positions: [
    { pair: 'ETHUSDT', leg: '0.5', entry: '1 834', pnl: 180 },
    { pair: 'SOLUSDT', leg: '0.382', entry: '168.4', pnl: 92 },
  ],
  periods: [
    { month: 'Июнь 2026', note: 'HWM $56K → equity $61.4K', amount: 812, open: true },
    { month: 'Май 2026', note: 'оплачено', amount: 540, open: false },
  ],
  cashflows: [{ label: 'Ввод $10 000', note: '02.06 · HWM ↑', sign: '+' }],
  contract: { hwm: '15%', period: 'месяц', currency: 'USDT', min: '$1000' },
}
