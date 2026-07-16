# pifagor-cartridge — картридж-обёртка Пифагора по Контракту Бота v1

Первый БОЕВОЙ движок за Контрактом. **Тонкий read-only адаптер** (ADR-0001) поверх вендоренного снимка
Пифагора `bots/pifagor/vendor/` (@`b75bd17`). Движок НЕ правим — читаем его состояние через его же
опубликованную агрегацию и транслируем команды в его опубликованные контролы. Эталон реализации
Контракта — `bots/paper-bot`.

## Как картридж реализует Контракт

**Телеметрия — через `dashboard.viewmodel.build_monitor` (Куратор #10, Вариант A).** Это та же функция,
что рисует РОДНОЙ дашборд Пифагора → цифры картриджа == цифры дашборда (faithfulness автоматическая,
доказана `tests/test_parity.py` на живом `build_monitor`). Адаптер подключается к БД воркера КАК дашборд:
`DB(owner=False)` — схему не создаёт, singleton-lock не берёт.

| Контракт (S4) | Источник Пифагора (build_monitor) |
|---|---|
| `heartbeat.status` | `killswitch_active`→`stopping` · `PAUSE_ENABLED`→`paused` · `stale`→`error` · иначе `running` |
| `equity` | `capital.equity` (+ `working`/`cushion`); `currency=USDT` |
| `trades[]` | `closed_trades`: `ts←created_ms` · `exec_id←dedup_key` · `side←Buy/Sell→buy/sell` · `pnl←closed_pnl` |
| `events[]` | `events`: `ts` (ISO воркера) · `kind←event` · `detail←parse(detail)+symbol` |

**Команды — в опубликованные контролы движка (не в правку кода):**
- `pause` → `ConfigStore.set("PAUSE_ENABLED", True)` — `app/cycle.py` гейтит вход, **позиции держатся**
  (семантика ADR-0005 pause). `resume` → `False`.
- `stop_close` → `killswitch.apply_state(STOP)` — durable-латч; `is_halted` гейтит цикл, движок гасит
  вход/отменяет незалитое и под `LIVE_TRADING_ENABLED` флэттит позиции (ADR-0005 stop_close). Картридж встаёт.

**4xx-классификация ОБЯЗАТЕЛЬНА (Куратор #6/#7).** В отличие от paper-bot (ретраит всё одинаково),
`app/client.py` различает: транзиентное (сеть/timeout, 408/425/429, 5xx) → backoff-ретрай; перманентное
(401/403/422 …) → лог + пропуск (НЕ долбим ядро); 413 → дробление батча. Курсоры trades/events двигаем
лишь при не-транзиентном исходе (at-least-once, ядро дедупит).

## Безопасный режим (гейт Ф2)
`LIVE_TRADING_ENABLED=0` (dry-run — брокера не трогаем, лог «поставил БЫ») + `BYBIT_DEMO=1` — дефолты
Пифагора. MAINNET доп. заперт `ALLOW_MAINNET`. Реальные ключи Bybit + живая торговля = **ОТДЕЛЬНЫЙ гейт
go-live** (только по явному «go» Оператора). `config.validate()` воркера требует demo-ключи (не боевые)
для БУТА движка; адаптер в одиночку ключей не требует.

## Модули
`app/config.py` env-конфиг · `app/client.py` CoreClient + классификация 4xx + backoff · `app/reader.py`
мост к БД/сторам Пифагора (build_monitor + контролы) · `app/mapper.py` чистый маппер build_monitor→Контракт
· `app/bot.py` цикл · `app/main.py` вход.

## Запуск / тесты
```
cd bots/pifagor-cartridge && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q        # unit (client/mapper/bot) + parity (реальный build_monitor)
.venv/bin/ruff check app tests
```
Образ (context = `bots/`): `docker build -f bots/pifagor-cartridge/Dockerfile -t mfc-pifagor-cartridge bots`

Вход по env (Контракт): `MF_INSTANCE_ID`, `MF_INSTANCE_TOKEN`, `MF_CORE_URL`. Локация БД воркера —
из вендоренного `config.ops` (`DATABASE_URL`/`DB_PATH`). `PIFAGOR_HOME` — путь вендора (в образе `/pifagor`).
