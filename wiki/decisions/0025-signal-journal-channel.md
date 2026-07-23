---
type: decision
title: ADR-0025 — Сигнальный журнал: канал телеметрии Этапа 1 (перекат 1-to-N)
tags: [adr, contract, signal-journal, telemetry, cartridge, pifagor, 1-to-N, phase5, s8]
updated: 2026-07-23
sources: [_curator/QUEUE.md, _curator/etap1-signal-journal-plan.md, _curator/architecture-1-to-N-compass.md, wiki/progress/s8-signal-journal.md, wiki/decisions/0016-scout-channel-onboard-scout.md, contracts/telemetry-signal-journal.schema.json]
---
# ADR-0025 — Сигнальный журнал: шестой канал Контракта (Этап 1 переката 1-to-N)

## Контекст
Перекат «1-to-N» (S8→Ф5): решения ОДНОГО ядра-характера (Борс) должны стать повторяемыми на СЧЕТАХ
клиентов (диспетчер Этапа 2). Нужна товарная запись КАЖДОГО решения ядра — replay-ready журнал.
Движок Пифагора уже пишет эти решения дискретно в свою worker-БД (`signals`/`fills`/`events`/
`closed_trades`, append-only, монотонный `id`), но до платформы они не доезжают faithful: адаптер
читает `build_monitor`, который режет окном recent-N (техдолг scroll-past-window) и не поверхностит
`signals`/`fills`. Пять каналов Контракта v1 (heartbeat/equity/trades/events/scout, ADR-0016) под
журнал решений не подходят: scout — replace-снимок (канбан), trades/events — торговая телеметрия, не
сырой журнал ядра-характера с натуральным ключом для повтора.

## Решение
Добавить **ШЕСТОЙ телеметрический канал `signal-journal`** — append-only ЖУРНАЛ дискретных решений
ядра-характера, зерно диспетчера повтора Этапа 2. Порция №3 канона Куратора.

### (а) Идемпотентность = натуральный ключ движка (вариант A, сверено по вендору)
Дедуп ЯДРОМ по `(instance_id, src_table, src_id)`. id строк worker-БД стабильны/монотонны (`MAX(id)+1`
под локом single-writer, журнальные таблицы НЕ прунятся) → пере-деривация после рестарта даёт ТЕ ЖЕ
ключи → `ON CONFLICT DO NOTHING`. `seq` — per-core ПОРЯДОК повтора (диспетчер Этапа 2), НЕ ключ дедупа.
Курсоры адаптера — оптимизация, не условие корректности.

### (б) Guard эпохи БД (fail-closed, обязателен)
Натуральный ключ верен лишь в пределах ОДНОЙ эпохи БД. Сброс (SQLite-фолбэк без Postgres / ре-провижн)
→ id новой эпохи коллидируют со старыми → тихая потеря. Адаптер держит per-table fingerprint
`(last_id, last_ts)`; на бооте перечитывает `id=last_id` — строки нет ИЛИ ts≠сохранённого → эпоха
сменилась → событие `service:journal_epoch_reset` (`src.table=adapter`) + алярм, курсор НЕ двигать
(parked). Транзиентный сбой ЧТЕНИЯ ≠ смена эпохи → ретрай без park (аудит 2026-07-23, F2). Ассерт:
прод + `DATABASE_URL` не Postgres → громкий алярм.

### (в) 0-vendor: движок не трогаем
Источник — курсорный direct-read worker-БД (`SELECT ... WHERE id>курсор`, `owner=False`, лок движка НЕ
берём). Ноль строк в `vendor/`, страж-дрейфа генома остаётся **3** санкц-дельты. Ведение-детали
(reanchor/stop_moved/scalp_removed — трогают вендор дискретной записью) — НЕ здесь: **вариант C →
будущий ADR-0024** (страж 3→4, отдельная подпись).

### (г) Семейства kind (сверено по вендор-коду, поправки П1–П4)
- **ВХОД:** `setup_detected` (← signals; вкл. cap-фильтр/dry-run; mb/tf движок не пишет → адаптер
  обогащает `provenance:adapter`, П4) · `setup_placed` (← events:setup_placed; реальная постановка —
  диспетчер Этапа 2 повторяет ТОЛЬКО это).
- **ВЕДЕНИЕ:** `leg_filled` (← fills; ЗАПРОШЕННЫЕ `requested_*`, exec не обещаем — опросный путь
  движка, П3) · `leg_exit` · `setup_ended` (← setup_closed[reason из detail: complete|timeout, П2] +
  close_all) · `trade_closed` (← closed_trades; реальный P&L Bybit) · `service` (catch-all прочих
  events движка — kill_switch_stop/warm_apply/idle_gap/worker_boot/orphan_*/ws_shadow_*, raw-имя в
  data; НИЧЕГО не дропаем — курсор мимо строки = потеря навсегда, П1).

### (д) Гейт и раскатка (fail-closed, как scout)
`SIGNAL_JOURNAL_ENABLED` дефолт **OFF** → флот/эталон байт-в-байт (чистый наблюдатель, торговлю не
меняет). `SIGNAL_JOURNAL_CORE` — метка ядра. **Борс ПЕРВЫМ** (обкатка формата); Персиваль — после
доказанной полноты, отдельная отмашка Оператор+Куратор.

## Механизм
- Схема `contracts/telemetry-signal-journal.schema.json` (v1, аддитивно): батч событий, `maxItems 500`
  (>500 → 413), конверт `schema_version/core/seq/ts/setup_id/kind/src{table,id}` + `data` (недоверенный
  JSON по kind). **Батч адаптера капнут ≤500** (`_BATCH_PER_TABLE = _CONTRACT_MAX_BATCH // len(_TABLES)`;
  бэклог дренится порциями лосслесс — устранение аудит-блокера 2026-07-23).
- Ядро: таблица `signal_journal` (миграция **0016**, append-only, uq натур. ключ) + маршрут
  `POST /v1/telemetry/signal-journal` (instance-токен, dedup, future-skew) + Pydantic-зеркало
  `SignalJournalIn` (sync-гвоздь + parity-тест enum/required) + readout'ы: `GET .../signal-journal/
  cursor` (instance-токен: max_seq + fingerprint для guard) и `GET /v1/instances/{id}/signal-journal`
  (operator-роль: лента).
- Картридж: `app/signal_journal.py::SignalJournalDeriver` (курсор-read → события → push, best-effort
  hook в `bot.tick`, различает транзиент/перманент ошибок ядра). Консоль: экран «Сигналы» (группа
  Журналы), недоверенный ввод рендерится ТОЛЬКО текстом.

## Последствия
- Контракт растёт до **6 каналов**; ядро принимает журнал как append-only запись с дедупом по
  натуральному ключу (не replace, не по seq).
- Появляется replay-ready костяк для Этапа 2 (повтор `setup_placed` на счёт клиента) — сам журнал
  НИЧЕГО не торгует.
- Полнота через курсор (не окно build_monitor) закрывает техдолг scroll-past-window в этой точке.
- Приёмка №3: 3–5 торговых дней на Борсе — каждая сделка/действие ↔ событие (экран ↔ карточка ↔
  биржа), 0 потерь/0 дублей, торговое поведение не изменилось.

## Триггер пересмотра
- **Вариант C (ведение ground-truth)** — reanchor/stop_moved/scalp_removed через мини-дельту
  `_log_event` в движке → **ADR-0024** (страж-дрейфа 3→4, подпись Куратора).
- Реальные исполнения (exec_price/fee) из `ws_exec_log` — инкремент после костяка (сейчас `leg_filled`
  несёт requested_*, П3).
- Раскатка на Персиваля/флот — после доказанной полноты на Борсе.
