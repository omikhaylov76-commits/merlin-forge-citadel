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
