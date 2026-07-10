# Контракт Бота v0 (обсуждаемый черновик)

## Вход (env при старте контейнера)
MF_INSTANCE_ID · MF_INSTANCE_TOKEN (скоуп: свой инстанс) · MF_CORE_URL ·
MF_PROFILE_JSON (или путь) · EXCHANGE, EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_ENV[demo|mainnet]

## Наружу (HTTP push в core, токеном инстанса)
POST /v1/telemetry/heartbeat   {status, uptime_s, note?}          — не реже раза в 60с
POST /v1/telemetry/equity      {ts, equity, working?, cushion?}
POST /v1/telemetry/trades      [{ts, symbol, side, qty, pnl, ...}]
POST /v1/telemetry/events      [{ts, kind, detail}]  kind: entry_filled|sl_moved|kill_switch|error|...

## Команды (бот опрашивает)
GET  /v1/commands/next?wait=25s → {cmd: none|pause|resume|stop_close, cmd_id}
POST /v1/commands/{cmd_id}/ack  {result}
Семантика stop_close: закрыть позиции безопасным путём движка, погасить процесс, статус STOPPED.

## Гарантии платформы
Секреты передаются один раз при старте; телеметрия принимается идемпотентно (dedup по ts+ключам);
пропуск heartbeat > 3 интервалов = алерт Оператору; команды идемпотентны (cmd_id).
