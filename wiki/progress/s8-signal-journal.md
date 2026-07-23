---
type: progress
title: S8 порция №3 — Сигнальный журнал (Этап 1 переката 1-to-N) — РАЗВЕДКА+ПЛАН на подпись
tags: [progress, s8, signal-journal, etap1, 1-to-N, telemetry, adr-0016, adr-0019]
updated: 2026-07-23
---

# Порция №3: Сигнальный журнал — РАЗВЕДКА завершена, план+схема НА ПОДПИСЬ Куратора

Родитель: `_curator/etap1-signal-journal-plan.md` (план Куратора) + `_curator/architecture-1-to-N-compass.md`.
Суть: каждое решение ядра-характера → строгое СОБЫТИЕ (товарная запись, replay-ready). Торговлю НЕ меняет —
чистый наблюдатель (0-vendor). Кода пока НЕТ — сперва подпись схемы (Контракт = домен Куратора).

## РАЗВЕДКА (что движок УЖЕ журналит — все таблицы worker-БД, append-only, монотонный `id`, курсор-абельны)
Писатели — `app/cycle.py:846–882` (`_log_signal/_log_fill/_log_event`, каждый в своём try/except, независимо от
LIVE_TRADING). Читатель `db.query(sql, params)` — общий (курсорные `WHERE id > ? ORDER BY id` законны).
- `signals` (`db.py:75`, put `:773`) — **ВХОД (детект)**: side, a/b, entry_0382/05/0618, stop, tgt_0382/05/0618,
  min_bar_pct, bar_time. Пишется на РОЖДЕНИИ сигнала (вкл. cap-фильтрованные и dry-run — т.е. НЕ все → на бирже).
- `events:setup_placed` — **ВХОД (реальная постановка)** (отличает поставленный от лишь детектированного).
- `fills` (`db.py:82`, put `:787`) — **нога залита (ТОЛЬКО входы**, `exec_type="entry"`, инвариант V7): entry_level,
  exec_price/qty, requested_*, slip_pct, risk_pct, nominal_usd, leverage_eff, partial, fee, order_id, order_link_id.
- `events:leg_exit` (`db.py:93`, структурные `lv/role/qty/exit_link/order_id`) — **выход ноги** (тейк role=tgt / стоп role=stp).
- `events:setup_closed / timeout / close_all / kill_switch_stop / refinance / worker_boot` — конец/протух/служебное.
- `closed_trades` (`db.py:135`) — **финал**: avg_entry, avg_exit, closed_pnl, qty, `dedup_key` UNIQUE, created_ms.

## ⚠️ ГАП (как в порции №2 — surface ДО кода)
1. **Покрытие:** `build_monitor` (единственная сейчас faithful-поверхность адаптера, `mapper.py`) отдаёт лишь
   `trades/events/pending/positions` — **`signals` и `fills` НЕ поверхностит**. Для журнала входов+заливов нужен
   иной путь чтения.
2. **Полнота:** `build_monitor` режет окном recent-N (events 50 / trades 200) → при всплеске/даунтайме теряет строки
   (известный техдолг scroll-past-window, `mapper.py:17-22`). Журнал-«ничего-не-потеряно» (приёмка п.1) на окне
   НЕСОСТОЯТЕЛЕН. ⇒ **Сигнальный журнал — естественный дом курсорного direct-read из worker-БД** (faithful: сырой
   журнал, не агрегат; 0-vendor: read-only SELECT по id-курсору в адаптере, вендор не трогаем, страж-дрейфа цел).
3. **Ведение НЕ журналится дискретно** (домен поправки Куратора «трейлинг/пере-якорь/скальп»):
   - **трейлинг-стоп** — только `log.info` (`executor.py:449/463`), эфемерно, в БД дискретного события НЕТ.
   - **пере-якорь** — новая сетка = новый `signals`-ряд + смена `setup_state`; отдельного «reanchor»-события нет.
   - **снятие скальпа** — видно лишь дельтой `setup_state`/`orders_open`.
4. **Нет нативного сквозного `setup_id` и единого `seq`**: у каждой таблицы свой `id`; связь сетап→заливы→выходы→
   финал — по `symbol` + `order_link_id`/`order_id` + окно. `setup_id` и per-core `seq` **конструирует адаптер**.

## РАЗВИЛКА Куратору по ведению (его домен: геном/вендор/схема) — как закрыть п.3
- **A. Дифф-деривация (адаптер, 0-vendor):** адаптер диффит снимки `setup_state`/`orders_open` тик-к-тику →
  синтезирует «стоп→X», «пере-якорь», «скальп снят». Плюс: 0 vendor, страж цел. Минус: инференс (не ground-truth),
  гранулярность = период опроса (промежуточные микро-сдвиги между тиками не ловятся).
- **B. Фазность:** Этап 1 отгружает журнал на ДИСКРЕТНЫХ событиях (входы/заливы/выходы/финал/служебные) — это уже
  replay-ready костяк для повтора; трейлинг/пере-якорь/скальп — следующим инкрементом (A или C). Плюс: чистая
  быстрая поставка 80%. Минус: не покрывает «критично» из плана сразу.
- **C. Мини-санкц-дельта вендора:** добавить ~3 вызова `_log_event(event="stop_moved/reanchor/scalp")` в движок
  (helper и таблица УЖЕ есть — правка крошечная, аддитивная) = **4-я санкц-дельта генома (ADR + страж 3→4)**.
  Плюс: ground-truth ведения (центр тяжести системы по компасу). Минус: трогает вендор → подпись Куратора + ADR.
- **Моя рекомендация: B сейчас + C следующим** (компас зовёт ведение критичным → ground-truth важнее инференса;
  но Этап 1 не держим на нём — костяк входов/заливов/выходов даёт формальную проверку полноты для Этапа 2).

## Предлагаемая СХЕМА событий (N-core-ready, replay — НА ПОДПИСЬ)
Конверт (общий): `core` (BORS/PERCEVAL/…), `instance_id`, `seq` (per-core монотонный, назначает адаптер),
`ts`, `setup_id` (адаптер: symbol+bar_time/link-prefix), `schema_version`, `kind`.
- **ВХОД `setup_detected`** ← `signals`: symbol, side, entries{0.382/0.5/0.618}, stop, targets{…}, mb(min_bar_pct),
  bar_time, tf. (placed=false для cap-фильтрованных).
- **ВХОД `setup_placed`** ← `events:setup_placed`: тот же сетап, факт постановки на биржу.
- **ВЕДЕНИЕ `leg_filled`** ← `fills`: entry_level(нога), exec_price, exec_qty, risk_pct, nominal_usd, leverage_eff,
  partial, order_id.
- **ВЕДЕНИЕ `leg_exit`** ← `events:leg_exit`: role(tgt/stp), lv, qty, exit_link, order_id.
- **ВЕДЕНИЕ `setup_closed`/`expired`** ← `events:setup_closed/timeout/close_all`: причина.
- **ВЕДЕНИЕ `trade_closed`** ← `closed_trades`: avg_entry, avg_exit, closed_pnl, qty, dedup_key.
- **Служебные** ← `events:kill_switch_stop`/пауза.
- **(если C)** `stop_moved`{new_stop} · `reanchor`{new_grid} · `scalp_removed`.

## Дизайн (0-vendor, если A/B; +дельта если C)
- **Источник:** новые курсорные ридеры в `PifagorReader` (`app/reader.py`) — SELECT по `id`-курсору из
  `signals/fills/events/closed_trades` (owner=False, лок не берём). Адаптер мержит по ts, назначает per-core `seq`,
  коррелирует `setup_id`. Курсоры персистит (возобновление без потери/дублей).
- **Хранение:** ядро — таблица `signal_journal` (миграция 0016, append-only, идемпотент по `(instance, core, seq)`,
  аддитивно). Маршрут `POST /v1/telemetry/signal-journal` (паттерн trades/events: дедуп ядром) + Pydantic-зеркало +
  readout. Отдельный канал (Закон 3; зеркало scout/engine-state).
- **Витрина:** мини-вкладка «Сигналы» в группе «Журналы» консоли — лента решений ядра (read-only, дёшево).
- **Раскатка:** Борс первым (обкатка формата); Персиваль — ПОСЛЕ доказанной полноты, отдельная отмашка Оператор+Куратор.

## Инварианты
- 0-vendor (вариант A/B; страж-дрейфа=3 неизменен). Вариант C = +1 санкц-дельта (ADR, страж 3→4) — только с подписью.
- Торговлю НЕ меняет (чистый наблюдатель) → регресс поведения Борса нулевой. 🔒 Демо. Персиваль/Галахад не тронуты.
- Полнота через курсор (не окно build_monitor) — закрывает техдолг scroll-past-window в этой точке.

## Порядок работ (после подписи схемы)
план+схема ⛔ подпись Куратора (Контракт-поле + развилка ведения A/B/C) → ветка → код (reader-курсоры + канал ядра
0016 + маршрут + вкладка) → тесты vs НАСТОЯЩИЙ вендор (курсор без потерь/дублей; идемпотентность seq) → сверка
полноты на живом Борсе (N дней: каждая сделка/действие ↔ карточка+биржа) → отчёт → гейт на Персиваля.

## Открытые вопросы Куратору
- (d1) Развилка ведения A/B/C (рекомендую B сейчас + C следующим).
- (d2) Формат `setup_id`: `symbol+bar_time` vs префикс `order_link_id` (подтвердить формат link_id при коде).
- (d3) Подпись поля Контракта `signal_journal` (новый канал телеметрии) — его домен.
- (d4) `signals` включает cap-фильтрованные/dry-run (детект ≠ постановка) — журналить оба (detected+placed) или только placed?

## ✍️ ФИНАЛЬНАЯ СХЕМА СОБЫТИЙ — ПОДПИСАНО + поправки Куратора (сверка по вендор-коду, QUEUE 2026-07-23)
Куратор подписал: d1 = **B костяк** + **C ведение потом** (ADR-0024; вар. A инференс НЕ берём); d3 поле Контракта ✅; d4 = detected И placed раздельно; **идемпотентность = вариант A (натуральный ключ движка)**; + 4 поправки схемы по сверке вендора (П1–П4) + guard эпохи БД.

**Конверт (все события; schema_version с 1-го дня):**
`schema_version` · `core` · `instance_id` · `seq` (per-core, ПОРЯДОК повтора — НЕ ключ) · `ts` · `setup_id` (`{symbol}:{bar_time}`) · `kind` · **`src`{table,id}** (натур. ключ движка = дедуп+провенанс).

**Семейство ВХОД:**
- `setup_detected` ← `signals` (вкл. cap-фильтр/dry-run): symbol, side, A, B, entries{0.382/0.5/0.618}, stop, targets{…}, bar_time. **mb+tf движок НЕ пишет (П4) → адаптер обогащает (provenance:adapter):** mb из coin_block, tf из SIGNAL_TF.
- `setup_placed` ← `events:setup_placed`: реальная постановка на биржу (сетка — из `signals` того же setup_id). **Диспетчер Этапа 2 повторяет ТОЛЬКО это.**

**Семейство ВЕДЕНИЕ (B-костяк — что движок пишет дискретно):**
- `leg_filled` ← `fills` (ТОЛЬКО входы): entry_level, **requested_price/requested_qty** (П3: exec_price/slip/fee/risk/nominal/leverage = NULL, опросный путь → НЕ обещаем exec; реальные — ws_exec_log, инкремент позже), order_id, order_link_id.
- `leg_exit` ← `events:leg_exit`: role(tgt/stp), lv, qty, exit_link, order_id.
- `setup_ended` ← `events:setup_closed` (reason=complete|timeout из detail) + `close_all` (П2: timeout — reason, НЕ отдельное событие).
- `trade_closed` ← `closed_trades`: symbol, side, qty, avg_entry, avg_exit, closed_pnl (реальный P&L Bybit).
- `service` (catch-all, П1) ← прочие `events`: kill_switch_stop/warm_apply/idle_gap/worker_boot/orphan_position/orphan_naked/ws_shadow_*, raw-имя в data. **Ничего не дропаем** (курсор мимо = потеря). orphan_* = аудит сирот.

**НЕ в B (→ C, ADR-0024, следующий шаг):** `stop_moved`(трейлинг) · `reanchor`(пере-якорь) · `scalp_removed` — движок дискретно не пишет; ground-truth через мини-дельту `_log_event`.

**Правила адаптера (ПОДПИСАНО, сверено по вендор-коду):**
- **Дедуп = натур. ключ `(instance, src.table, src.id)`** (id worker-БД стабильны/монотонны — MAX(id)+1, не прунятся) → пере-дерив идемпотентен БЕЗ durable-состояния (вар. A). `seq` — лишь порядок повтора.
- **Guard эпохи БД (fingerprint, ОБЯЗАТЕЛЕН):** персист `(last_id,last_ts)` per-table; на бооте перечитать `id=last_id` — нет строки ИЛИ ts≠сохр. → эпоха сменилась (SQLite-фолбэк / ре-провижн) → событие `journal_epoch_reset` + алярм, курсор НЕ двигать. + ассерт: прод + `DATABASE_URL`≠postgres → громкий алярм.
- `setup_id = {symbol}:{bar_time}` (bar_time из signals). Пере-якорь (C) родит новый `setup_detected`/setup_id; fills/exits остаются на ИСХОДНОМ активном setup_id — консистентно для B.
- Курсоры per-table — ОПТИМИЗАЦИЯ (корректность даёт натур. ключ, не курсор).

**Источник (0-vendor):** курсорный direct-read worker-БД по `id` (`db.query("SELECT * FROM {tbl} WHERE id>%s ORDER BY id", (cur,))`, owner=False). Вендор не трогаем, страж-дрейфа=3.
**Ядро:** таблица `signal_journal` (миграция 0016, append-only), идемпотент по `(instance_id, src_table, src_id)`, аддитивная. Маршрут `POST /v1/telemetry/signal-journal` + Pydantic-зеркало (schema-first) + readout. Зеркало scout/engine-state (Закон 3).
**Витрина:** мини-вкладка «Журнал» (Сигналы) в группе «Журналы» консоли (read-only лента).

## Код — под-шаги (ветка `task/s8-signal-journal`)
- [x] 1. Контракт-схема `contracts/telemetry-signal-journal.schema.json` (конверт+kind+data, examples).
- [x] 2. Ядро-приём: модель `SignalJournalEvent` + миграция `0016_signal_journal` (append-only, uq(instance,seq))
      + Pydantic `SignalJournalIn` + маршрут `POST /v1/telemetry/signal-journal` (dedup, `_check_future_skew`)
      + sync-гвоздь тест. ruff чист, core **34 passed**.
- [x] 3. Адаптер: `app/signal_journal.py` — SignalJournalDeriver (курсор-read 4 таблиц по `id` →
      деривация по подписям П1–П4 + fingerprint-guard эпохи fail-closed + посев active из setup_state
      + seq-резюм из ядра) + `client.push_signal_journal`/`get_signal_journal_cursor` + гейт
      `SIGNAL_JOURNAL_ENABLED` (дефолт ВЫКЛ — флот байт-в-байт) + hook в `bot.tick` (best-effort) +
      обвязка `main._make_journal` (+ассерт Куратора про Postgres). **Тесты vs НАСТОЯЩИЙ вендор: 13**
      (жизнь сетапа 6 событий · П2/П3/П4 · service catch-all П1 · курсор no-dup/no-loss · пере-дерив
      те же ключи · seq-резюм · эпоха: строка исчезла/ts разошёлся → parked+reset · unknown-фоллбэк ·
      close_all[ALL]→service). Картридж **252 passed**, ruff чист.
- [x] 4. Readout'ы ядра: `GET /v1/telemetry/signal-journal/cursor` (instance-токен: max_seq +
      per-table fingerprint — guard эпохи) + `GET /v1/instances/{id}/signal-journal` (operator: лента).
- [x] 5. Консоль: экран «Сигналы» (группа Журналы) — лента событий (`getSignalJournal`, селектор бота,
      авто-обновление 10с, русская лексика типов из фактов, пусто/грузится/ошибка, недоверенный ввод
      ТОЛЬКО текстом). tsc чист; рендер проверен вживую (пустое состояние + навигация, 0 ошибок консоли).
- [~] 6. code-review → ⛔ merge в main → деплой Борса (`SIGNAL_JOURNAL_ENABLED=1`+`SIGNAL_JOURNAL_CORE=BORS`)
      → сверка полноты N дней. **Аудит пройден** (code-review + 3 угла швы/архитектура/черви, 5 агентов):
      🔴 батч-клин >500 найден+починен (кап `_BATCH_PER_TABLE=500//4=125` +регресс-тест) + 🟡 Н1/Н2/F1/F2/F4.
      Заключение Куратора: аудит принят → **ADR-0025** (6-й канал) + строка в `telemetry-schemas.md` +
      parity-тест enum/required добавлены. Ветка @ `fc52d8e`→доп-коммиты. Тесты: журнал 15 / картридж 254 /
      core 35, ruff/tsc чисты. ⛔ Ждёт merge (слово Оператора) → деплой спокойным окном (Борс первым).

## SHA
- Разведка + финальная схема + КОД под-шаги 1–2 (ядро-приём): 2026-07-23 (эта сессия). Куратор подписал
  d1(B+C)/d3/d4 + setup_id/seq. Ветка `task/s8-signal-journal`. Дальше — адаптер (курсор-read) + консоль.
