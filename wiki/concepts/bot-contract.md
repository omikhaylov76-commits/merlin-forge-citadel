# Контракт Бота v1 (обсуждаемый черновик; scout-канал — ADR-0016, бамп v0→v1)

## Вход (env при старте контейнера)
MF_INSTANCE_ID · MF_INSTANCE_TOKEN (скоуп: свой инстанс) · MF_CORE_URL ·
MF_PROFILE_JSON (или путь) · EXCHANGE, EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_ENV[demo|mainnet]

## Наружу (HTTP push в core, токеном инстанса)
POST /v1/telemetry/heartbeat   {status, uptime_s, note?}          — не реже раза в 60с
POST /v1/telemetry/equity      {ts, equity, working?, cushion?}
POST /v1/telemetry/trades      [{ts, symbol, side, qty, pnl, ...}]
POST /v1/telemetry/events      [{ts, kind, detail}]  kind: entry_filled|sl_moved|kill_switch|error|...
POST /v1/telemetry/scout       [{symbol, tf, state, levels[], klines[], orders[], position, ...}]  — снимок сетапов (v1, ADR-0016; replace-семантика; ручка/таблица — #52)

## Команды (бот опрашивает)
GET  /v1/commands/next?wait=25s → {cmd: none|pause|resume|stop_close, cmd_id}
POST /v1/commands/{cmd_id}/ack  {result: ok|error, detail}
Семантика stop_close: закрыть позиции безопасным путём движка; result=ok → погасить процесс,
статус stopped; result=error → НЕ гасить, ручное закрытие (flows Б). Пока instance в stopping —
/commands/next «липко» отдаёт stop_close (OPS1). **КАНОН списка команд: pause · resume · stop_close**
(start не существует — бот стартует env'ом). Иные формулировки в ADR-0001/0002/глоссарии — устаревшие.

## Гарантии платформы
Секреты передаются один раз при старте; телеметрия идемпотентна (dedup: trades по (instance, exec_id
биржи); equity/events по (instance, ts, kind) — НЕ по одному ts, иначе теряются со-секундные сделки, COH4);
пропуск heartbeat > 3 интервалов = алерт; команды идемпотентны (cmd_id = UUID).

## Обязанности картриджа (уточнения MFC-000)
- Свободные поля (detail/note/symbol) — НЕДОВЕРЕННЫЙ ввод: платформа их экранирует, но картридж
  не шлёт исполняемое; equity — строго в USDT (unified-оценка), поле currency обязательно (MON9).
- Картридж раз в сутки проверяет права своего ключа (он у него в env) и шлёт event kind=key_perms
  {withdraw_enabled}; включённый вывод → алерт + автопауза (SEC3 — так проверка не нарушает закон №2).
- Движок сам мигрирует свою схему в БД ботов при старте; pool_size ≤ 2 (SCL2).
