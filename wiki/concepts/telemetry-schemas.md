# Схемы телеметрии Контракта Бота (v1, MFC-005 · ADR-0016)

Schema-first: схема — источник истины, код по ней. Живут в `contracts/*.schema.json` (JSON Schema
2020-12, `$id` с версией `v1` — бамп v0→v1 в ADR-0016, добавлен scout-канал). Pydantic-модели ядра
(`app/routes_telemetry.py`) — их зеркало для торговых каналов; sync-тесты
(`core/tests/test_contracts_schemas.py`, `test_telemetry.py`) гвоздят: схемы валидны, их examples
проходят и принимаются моделями. Правка схемы = новая версия контракта (роняет sync-тест, если модель
не обновили). Версия-синк в обоих картриджах (`tests/test_contract_version.py`): `CONTRACT_VERSION` ==
версия из `$id` схем. **Pydantic-зеркало scout-снимка — на стороне ядра-приёмника (#52)** (картриджи
намеренно без pydantic — снимок ПРОИЗВОДЯТ и валидируют jsonschema); enforcement версии в ядре отложен.

Каналы (S4→, токен инстанса): **heartbeat** {status, uptime_s, contract_version, note?} — освежает
last_heartbeat_at (+starting→running); **equity** {ts, equity, currency=USDT, working?, cushion?} —
dedup (instance, ts); **trades[]** {ts, exec_id, symbol, side, qty, pnl?} — dedup (instance, exec_id,
COH4); **events[]** {ts, kind, detail?} — dedup (instance, ts, kind); **scout** (v1, ADR-0016) —
движко-нейтральный СНИМОК сетапов per (instance, symbol, tf), **replace-семантика** (upsert, не append):
{symbol, tf, state, levels[{role,price}], score, bars_since_anchor, klines[≤500], klines_tf, orders,
position, scan_ts, …, config_mismatch{flag,details}, producer}; приёмная ручка/таблица/readout — #52.
Аддитивные поля S8: `verified` (F-scout-snap: levels = сетка сделки движка для held) и `engine`
(единая Разведка, подпись Куратора 22.07: ПРАВДА ДВИЖКА per-coin — факты warm.classify {kind
PENDING|OPEN|null, auto_eligible, reanchored, in_universe, side?, age_bars?, entries?, stop?,
targets?, est_risk_pct?}; ключа нет = правда не посчитана, «неизвестно» ≠ «не берёт»; снимок
скаута, не живой тик — лексика причин выводится консолью из фактов).
Команды (S4←): **command** {cmd: none|pause|resume|stop_close, cmd_id}. Приём —
[core-api](core-api.md) §Контракт Бота, поток — [flows](flows.md).
