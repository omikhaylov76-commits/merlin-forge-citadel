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

## План Ф2 (по маршруту DIRECTIVES)
- [~] 1. Recon-2: телеметрия БЕЗ dashboard (viewmodel не вендорен) — тянуть equity/curve из CapitalStore/
       Ledger, сделки из realised-журнала (state/storage), health из killswitch/capital. Точки управления:
       pause/stop_close → `risk_capital.killswitch` + config (kill-switch есть в живом субсете).
- [ ] 2. ADR: архитектура обёртки (образ = снимок Пифагора @b75bd17 + тонкий адаптер; адаптер импортирует
       viewmodel/storage read-only, пушит по Контракту, команды→контролы). Развилки — в QUEUE.
- [ ] 3. Адаптер телеметрии (bots/pifagor-cartridge/ — тонкий, НЕ копия Пифагора): цикл heartbeat ≤60с +
       build_monitor→equity/trades/events + poll команд→pause/stop_close. Тесты на маппинг (мок viewmodel).
- [ ] 4. Образ-обёртка: Dockerfile, что клонирует/монтирует Пифагор @b75bd17 + ставит адаптер; сборка.
- [ ] 5. Конверт-шифрование ключей биржи end-to-end (ADR-0004/0010) + тесты — ⛔ реальные ключи только по
       отдельному «go» Оператора (граница DIRECTIVES); в обкатке — demo/paper.
- [ ] 6. Живой сквозняк: копия Пифагора (demo, без реальных денег) как картридж → телеметрия в ядро,
       kill-switch через портал/оператора. Затем сдача миссии.

## Границы
pifagor-v81 не трогать (только чтение/клон). Реальные ключи/деньги — только после «go» (Контракт: demo-
форвард Пифагора сначала). Конверт ключей (ADR-0010) — до любого реального ключа.
