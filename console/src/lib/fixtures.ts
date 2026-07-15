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
export const clientsFixture: {
  name: string
  fav: boolean
  capital: number
  gild: boolean
  sub: string
  meta: string[]
  toBill: number
  note: string
}[] = [
  { name: 'Клиент-01', fav: true, capital: 42100, gild: true, sub: 'net +$3.1K · HWM $39K', meta: ['2 бота', '3 сделки', 'DD 22%'], toBill: 465, note: '7 дн до закрытия' },
  { name: 'Клиент-11', fav: true, capital: 61400, gild: true, sub: 'net +$5.4K · HWM $56K', meta: ['1 бот', '1 сделка', 'DD 18%'], toBill: 812, note: 'ключ ⚠ 3 дня' },
  { name: 'Клиент-03', fav: false, capital: 28300, gild: false, sub: 'net −$0.3K · HWM $30K', meta: ['1 бот', '2 сделки', 'DD 38%'], toBill: 0, note: 'под HWM' },
  { name: 'Клиент-07', fav: false, capital: 18050, gild: false, sub: 'net −$2.0K · стоп сработал', meta: ['1 бот', 'стоп', 'DD 51%'], toBill: 0, note: 'разобрать' },
  { name: 'Клиент-02', fav: false, capital: 15900, gild: false, sub: 'пауза · HWM $16K', meta: ['1 бот', 'пауза'], toBill: 0, note: '—' },
]
