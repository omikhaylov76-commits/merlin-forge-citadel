# pifagor — картридж движка Пифагор (Ф2)

Первый БОЕВОЙ движок за Контрактом Бота v0. Тонкий read-only адаптер поверх ВЕНДОРЕННОГО снимка
Пифагора. Оригинал `pifagor-v81` НЕ трогаем никогда (закон №6); интеграция — только адаптером
телеметрии (эталон реализации Контракта — `bots/paper-bot`).

## Снимок (пин)
- Источник: свежий `git clone https://github.com/omikhaylov76-commits/pifagor-v81.git` (приватный, аккаунт
  Оператора), `checkout b75bd17`. НЕ из локальной папки (там iCloud-офлоад/локи → «Resource deadlock avoided»).
- **Коммит: `b75bd176193abba1803899c092052c1f9c00a9eb`** (b75bd17, «паспорт V8.3»: трейл C3/C4 + R8-продуктизация).
  Подтверждён Оператором + Куратором (DIRECTIVES #9) 2026-07-11.
- Временный клон и его `.git` удаляются после вендора — здесь только субсет-код, без истории Пифагора.

## Что вендорено (`vendor/`) — по РЕАЛЬНОМУ живому графу импортов
Живой путь (`app/main.py` → `app/cycle.py` → …) тянет: **app · broker · config · execution · logging_ ·
market · risk_capital · scout · state · storage · strategy** (+ `requirements.txt`, `runtime.txt`).
Живой движок стратегии — `vendor/strategy/engine/pifagor_fib_backtest_v2_clean`. kill-switch —
`vendor/risk_capital/killswitch` (пригодится для команды stop_close).

**+ `dashboard/{__init__,viewmodel}.py`** (session 5, recon-2, DIRECTIVES #10 Вариант A): агрегация
`build_monitor(...)` отдаёт РОВНО телеметрию Контракта (equity/curve/cushion/kill-switch/сделки/health) —
адаптер читает через неё → цифры картриджа == родной дашборд Пифагора (faithfulness автоматическая).
Import-замыкание `viewmodel.py` = `{config, json, logging_, time}` (без Flask/UI) — выделяется чисто.
Вендорены ТОЛЬКО эти два файла (не `dashboard.py`/`prices.py`/`static/`/`templates/`). sha256 сверены
с клоном и локалью @b75bd17 (идентичны).

**НЕ вендорено (и почему):** `engine/` — это движок-ЭТАЛОН (parity-источник для бэктестов), живым путём
НЕ импортируется → хлам для картриджа; `dashboard/dashboard.py`(FastAPI-кокпит)/`prices.py`/`static/`/
`templates/` — у платформы своя консоль (кокпит Пифагора S9 — прокси позже; берём лишь агрегацию-viewmodel);
`legacy_bot_reference/`, `backtest/`; `railway.json`/`start.sh` Пифагора (у нас свой Контракт-env и деплой);
`pifagor.db`/`*.lock` (рантайм-состояние).

⚠️ **Отклонение от эвристического списка Куратора (#7) — по его же указанию «проверь по реальным
импортам».** #7 называл «engine», не называл «app»/«state». Трасса живого графа показала обратное:
top-level `engine/` живым путём не нужен (эталон), а `app/` и `state/` — обязательны. Вынесено в QUEUE
на разбор. Оригинал не тронут; всё воспроизводимо из пина.

## Дальше (план — progress/f2-pifagor-cartridge.md)
Recon-2 ✅ (session 5): телеметрия — через вендоренный `build_monitor` (Вариант A). Далее: адаптер
`bots/pifagor-cartridge/` по Контракту (heartbeat ≤60с, equity/trades/events, pause→PAUSE_ENABLED /
stop_close→killswitch; **4xx-классификация транзиентное/перманентное + backoff обязательна**) +
parity-тест (#10) → образ → деплой Railway в БЕЗОПАСНОМ режиме (без реальных ключей, go-live отдельно).
