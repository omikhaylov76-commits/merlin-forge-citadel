---
type: progress
title: Ф2 — картридж-обёртка Пифагора (первый боевой движок за Контрактом)
tags: [progress, phase-2, pifagor, bot-contract, cartridge, wrapper]
updated: 2026-07-11
sources: [_curator/DIRECTIVES.md, concepts/bot-contract.md, decisions/0001, 0004, 0010]
---
# Ф2 — картридж-обёртка Пифагора

**Цель веха.** Первый боевой движок (Пифагор) за Контрактом Бота v0, БЕЗ правок pifagor-v81 (закон №6).
Платформа гоняет копию Пифагора как первый картридж. Точка сдачи миссии Ф1→Ф2.

**Снимок (подтверждён Оператором «поехали» 2026-07-11).** Репозиторий `~/Desktop/pifagor-v81`, ветка
`main`, **коммит `b75bd17`** (HEAD; дерево чистое; свежие фичи C3/C4/R8 помечены done — «самый актуальный»).
Снимок = ПИН этого коммита; физический frozen-клон делаем в образе обёртки (не копируем код Пифагора в
этот репо — закон №6). Оригинал НЕ трогаем никогда (только чтение).

## Recon (read-only, выполнен) — допущение «обёртка без правок репо» ✅ ПОДТВЕРЖДЕНО
- Пифагор V8.1 зрелый: вехи 1–4 отгружены, 330 тестов, уже Railway-деплоим (`railway.json`/`start.sh`/
  `requirements.txt`). Слои: `app/`(main,cycle) `strategy/ execution/ broker/ risk_capital/ storage/db.py
  dashboard/`. `engine/` — эталон-parity.
- **`dashboard/viewmodel.py::build_monitor(db, capital_store, config_store, state_store, …)`** отдаёт ровно
  телеметрию Контракта: equity + `curve`(ts_ms, equity), working/cushion/ratio/peak, dd_pct/kill_dd/
  below_kill (kill-switch), realised-журнал (сделки), health/zone/stale. → адаптер ЧИТАЕТ это и мапит в
  heartbeat/equity/trades/events, движок не правя.
- Команды S4 (pause/stop_close) ложатся на СВОИ механизмы Пифагора (kill-switch/config_store) — это
  единственная точка «записи», и она через ОПУБЛИКОВАННЫЙ контроль движка, не через правку кода (уточнить
  API kill-switch в след. recon).

## Снимок + вендор — СДЕЛАНО (ветка task/f2-pifagor-cartridge)
Свежий клон github pifagor-v81 @ b75bd17 → вендорен ЧИСТЫЙ живой субсет в `bots/pifagor/vendor/` (66
файлов): app/broker/config/execution/logging_/market/risk_capital/scout/state/storage/strategy +
requirements/runtime. По РЕАЛЬНОМУ графу импортов: `engine/` (эталон/бэктест) выкинут как хлам;
`state/`+`app/` добавлены (обязательны живым путём) — отклонение от эвристики #7, в QUEUE. dashboard/
legacy/backtest/db/lock не взяты. Клон удалён. Детали — bots/pifagor/README.

## Recon-2 (read-only, выполнен 2026-07-11 session 5) ✅ — РЕШЕНИЕ #10 Вариант A
Куратор #10 дал развилку: если `build_monitor` выделяется дёшево (без тяжёлых UI-зависимостей) —
вендорить ТОЛЬКО агрегацию и читать через неё (паритет автоматический); иначе — читать из state/storage
+ обязательный parity-тест. **Проверено на оригинале @b75bd17 (read-only): выделяется ЧИСТО.**
- `dashboard/viewmodel.py` — import-замыкание ровно `{config, json, logging_, time}` (stdlib + вендорено).
  `dashboard/__init__.py` — 2 строки docstring, БЕЗ Flask. Ссылки на `dashboard.*` только в комментариях.
  → вендорим ТОЛЬКО `dashboard/{__init__,viewmodel}.py` (агрегация), НЕ `dashboard.py`(Flask)/prices/static/templates.
- **Телеметрия через `build_monitor(db, capital_store=, config_store=, state_store=, prices=None)`** (Вариант A):
  faithfulness автоматическая — картридж считает те же цифры, что родной дашборд. Возвращает вложенный dict
  `status/capital/tiles/trades/events/equity_curve/...`. Безопасные числа (dd/kill-switch/state) — на биржевом
  снимке, НЕ зависят от `prices` (можно `prices=None` → equity fail-soft к снимку леджера).
- **Маппинг в Контракт v0** (эталон = paper-bot, канон команд none·pause·resume·stop_close):
  - heartbeat.status: PAUSE_ENABLED→`paused`; killswitch_active→`stopping`; stale→`error`; иначе `running`.
  - equity: `{ts, equity=capital.equity, currency=USDT, working, cushion}` (заголовочное число тайла).
  - trades ← `closed_trades`(ts←created_ms→ISO, exec_id←dedup_key UNIQUE, symbol, side, qty>0, pnl←closed_pnl).
  - events ← `events`(ts←ts_ms→ISO, kind←event, detail←parse(detail)+symbol). Дедуп ядром по exec_id / (ts,kind).
- **Контролы (ADR-0001 read-only, опубликованные механизмы Пифагора, движок НЕ правим):**
  - pause → `config_store.set("PAUSE_ENABLED", True)`; resume → `set(..., False)`. Cycle гейтит `eff["PAUSE_ENABLED"]`
    (стоп новых входов, позиции держатся = семантика ADR-0005 pause). Есть даже штатная АВТО-ПАУЗА (cycle.py:803).
  - stop_close → `killswitch.apply_state(capital_store, "STOP")` (durable-латч, `is_halted` гейтит cycle); resume-
    из-стопа → `clear_killswitch`. Флэттен открытых позиций делает движок под `LIVE_TRADING_ENABLED` (в dry-run — лог).
- **Store-проводка:** адаптер строит `DB(owner=False)`+ConfigStore+StateStore+CapitalStore — как дашборд
  (читает БД воркера БЕЗ singleton-лока, `app/main.py:89`). owner=False = не создаёт схему, лок не берёт.
- **Безопасный режим НАТИВЕН:** `LIVE_TRADING_ENABLED=False`(dry-run, брокера не трогает) + `BYBIT_DEMO=True` —
  дефолты. MAINNET двойной предохранитель (`ALLOW_MAINNET`). НО `config.validate()` требует BYBIT_API_KEY/SECRET
  для БУТА ВОРКЕРА (demo-ключи, не реальные деньги); **адаптер в одиночку (читает засеянную БД) ключей НЕ требует**
  → сквозняк телеметрии/команд доказуем без ключей. (Развилка «как образ гоняет воркер+адаптер в safe» — в QUEUE.)

## План Ф2 (по маршруту DIRECTIVES, уточнён recon-2)
Последний коммит ветки: ce66543
- [x] 1. Recon-2: источники телеметрии/контролов (см. выше) — Вариант A подтверждён (session 5).
- [x] 2. Вендор `dashboard/{__init__,viewmodel}.py` @b75bd17 из свежего клона (sha сверены) — 59e0619.
- [x] 3. Адаптер `bots/pifagor-cartridge/` (тонкий, НЕ копия Пифагора): CoreClient + **4xx-классификация
       транзиентное/перманентное + backoff (#6/#7)** + маппер build_monitor→Контракт + цикл heartbeat ≤60с +
       poll команд→pause/resume/stop_close. 58 юнит-тестов (client/mapper/bot) зелёные, ruff clean.
- [x] 4. **Parity-тест (#10):** адаптерная телеметрия == `build_monitor(b75bd17)` на засеянной SQLite —
       снимок ридера == прямой build_monitor + faithful маппинг + контролы бьют в killswitch/config. 4 теста.
- [~] 5. Образ-обёртка: Dockerfile (context=bots/: vendor→/pifagor + адаптер) + start.sh (движок dry-run demo
       + адаптер) + .dockerignore. Safe-режим (LIVE_TRADING_ENABLED=0/BYBIT_DEMO=1). Локальная сборка — след.
- [ ] 6. Деплой Railway тем же конвейером (безопасный режим, БЕЗ реальных ключей) → сквозняк телеметрии+команд →
       доложить Куратору. ⛔ реальные ключи/торговля = отдельный гейт go-live.
- [ ] 7. (отложено, гейт go-live) Конверт-шифрование ключей биржи end-to-end (ADR-0004/0010) + тесты.

## Границы
pifagor-v81 не трогать (только чтение/клон). Реальные ключи/деньги — только после «go» (Контракт: demo-
форвард Пифагора сначала). Конверт ключей (ADR-0010) — до любого реального ключа.
