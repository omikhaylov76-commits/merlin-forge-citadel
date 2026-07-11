# Схемы телеметрии Контракта Бота v0 (MFC-005)

Schema-first: схема — источник истины, код по ней. Живут в `contracts/*.schema.json` (JSON Schema
2020-12, `$id` с версией `v0`). Pydantic-модели ядра (`app/routes_telemetry.py`) — их зеркало;
sync-тесты (`core/tests/test_contracts_schemas.py`, `test_telemetry.py`) гвоздят: схемы валидны, их
examples проходят и принимаются моделями. Правка схемы = новая версия контракта (роняет sync-тест,
если модель не обновили).

Каналы (S4→, токен инстанса): **heartbeat** {status, uptime_s, contract_version, note?} — освежает
last_heartbeat_at (+starting→running); **equity** {ts, equity, currency=USDT, working?, cushion?} —
dedup (instance, ts); **trades[]** {ts, exec_id, symbol, side, qty, pnl?} — dedup (instance, exec_id,
COH4); **events[]** {ts, kind, detail?} — dedup (instance, ts, kind). Команды (S4←): **command**
{cmd: none|pause|resume|stop_close, cmd_id}. Приём — [core-api](core-api.md) §Контракт Бота, поток — [flows](flows.md).
