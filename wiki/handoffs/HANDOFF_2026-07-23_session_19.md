---
type: handoff
title: HANDOFF 2026-07-23 session 19 — S8 порция №3 «Сигнальный журнал» ВЕСЬ КОД готов (ветка) + аксиома пере-якоря + Борс/Персиваль на V3
tags: [handoff, s8, signal-journal, 1-to-N, reanchor-axiom, v3, dinamo-bliznec]
updated: 2026-07-23
---

# HANDOFF 2026-07-23 · session 19

## Состояние
**S8→Ф5, перекат 1-to-N.** Канон Куратора: порции №1 (бары ✅) · №2 (прогрев held ✅) ·
**№3 «Сигнальный журнал» — ВЕСЬ КОД ГОТОВ на ветке `task/s8-signal-journal`, НЕ влит, ждёт
code-review → merge → деплой Борса.** Плюс за сессию: **аксиома пере-якоря** зафиксирована,
**Борс И Персиваль переведены на V3** (демо, живьё). main @ **19d2bcc** (доки/аксиома/V3/техдолг),
ветка @ **0d99c53** (код №3, запушена). 🔒 демо, стражи не тронуты.

## Сделано в сессии (марафон)
1. **Вики-бухгалтерия S18 + /status + чек-лист** — всё зелёное (Борс жив, тесты, страж-дрейфа=3).
2. **Диагностика WLFI (пере-якорь «не сработал»):** прогнал НАСТОЯЩИЙ `warm.classify` на реальных
   публичных 4h-свечах Bybit → сетап поставлен ВЕРНО (A/B/сетка точь-в-точь биржа). Корень «не
   сработало» = **env-флаг вступает в живой процесс только при РЕДЕПЛОЕ** (переменная V3, процесс
   крутил стейл-V2).
3. **Аксиома пере-якоря зафиксирована** (V3 окончательная; V2 устарела) — `entities/pifagor-engine.md`
   + память. Правило: новый хай→пере-якорь ВСЕГДА пока не закоммичен; после скальпа 0.382 продолжает;
   заморозка ТОЛЬКО при касании 0.5 (commit). Код `execution/lifecycle.py:191/256/265/269`.
4. **Борс→V3** (redeploy, `rw_deploy_bors.py`) + **Персиваль→V3** (решение Оператора, Куратор подписал;
   узкий `rw_deploy_persival.py`, только флаг REANCHOR, стражи ДО==ПОСЛЕ, боот чистый флэт).
5. **Техдолг** (запрос Оператора): живая цена позиций из публичного Bybit + свежесть карточки —
   Icebox + `_curator/tech-debt.md`.
6. **🏁 Порция №3 «Сигнальный журнал» — ВЕСЬ КОД** (разведка→схема→ядро→адаптер→readout→консоль).

## Решения сессии
- **Аксиома пере-якоря V3** = доменное правило движка (в `entities/pifagor-engine.md`, НЕ ADR).
- **Порция №3:** идемпотентность = **вариант A (натуральный ключ движка `(instance, src_table,
  src_id)`)**; ведение = **B-костяк сейчас** (дискретные события) **+ C потом** (reanchor/trail/scalp
  = отдельная санкц-дельта, **ADR-0024 — ещё НЕ оформлен, будущее**). Куратор сверил по вендор-коду
  → 4 поправки (П1 service-catch-all · П2 reason из detail · П3 requested_* не exec · П4 mb/tf
  provenance:adapter) + guard эпохи БД (fingerprint) — всё вшито.
- **Персиваль→V3** (Оператор; Куратор принял «со звёздочкой»). Флот-раскатка + амендмент ADR-0014 +
  Малыш Мерлин b75bd17 — **в техдолг, НЕ трогаем** (эталон замороженный).

## Код
- **main @ `19d2bcc`** (запушено): вики-бухгалтерия S18, аксиома (`pifagor-engine.md`+память),
  V3-факты, техдолг, разведка+черновик схемы №3. Незакоммиченного нет.
- **Ветка `task/s8-signal-journal` @ `0d99c53`** (запушена, 4 коммита впереди main, **НЕ влита**):
  `d814aee` ядро-приём · `cde0e1c` поправки Куратора (натур.ключ+П1-П4) · `ef1deb6` адаптер+readout ·
  `0d99c53` консоль. **Незакоммиченного МОЕГО нет.** (В `git status` висят pre-existing iCloud-дубли
  `… 2.py/.tsx/.md` — НЕ мои, были с начала сессии, не трогать.)
- Ops-скрипты `orchestrator/rw_deploy_bors.py`+`rw_deploy_persival.py` — gitignored (локальные).

## Порция №3 — что построено (все под-шаги 1–5, тесты зелёные)
- Схема `contracts/telemetry-signal-journal.schema.json` (конверт core/instance/seq/ts/setup_id/
  schema_version + kind + `src`{table,id} + data).
- Ядро: `SignalJournalEvent` + миграция `0016_signal_journal` (append-only, uq натур.ключ) + маршрут
  `POST /v1/telemetry/signal-journal` + Pydantic + sync-гвоздь + readout'ы (`GET .../signal-journal/
  cursor` instance-токен для guard; `GET /v1/instances/{id}/signal-journal` operator для ленты).
- Адаптер: `app/signal_journal.py` `SignalJournalDeriver` (курсор-read 4 таблиц по id → события +
  fingerprint-guard эпохи fail-closed + посев active из setup_state + seq-резюм из ядра) +
  `client.push_signal_journal`/`get_signal_journal_cursor` + гейт `SIGNAL_JOURNAL_ENABLED` (дефолт
  ВЫКЛ) + hook в `bot.tick` (best-effort) + `main._make_journal`.
- Консоль: экран `screens/Signals.tsx` (группа Журналы → «Сигналы»), `getSignalJournal`, авто-обн 10с.
- **Тесты:** картридж **252 passed**, core **34 passed**, журнал **13 vs НАСТОЯЩИЙ вендор**, ruff/tsc
  чисты, экран проверен вживую (0 ошибок консоли).

## Живой прод
- **Ядро** `core-production-429b.up.railway.app` (healthz 200). Миграция 0016 **НЕ применена**
  (на ветке; применится с деплоем ядра при merge).
- **Борс `cd8d0534`** — V3 + прогрев held + cap=24, `DYNAMIC_SOURCE=engine`/`LIVE=1`/`BYBIT_DEMO=1`.
  Сигнальный журнал ВЫКЛ (гейта нет до деплоя ветки).
- **Персиваль `a6df714f`** — V3 (классик, cap=16). **Галахад `dd7427a5`** не тронут.
- **Консоль** `console-production-f533.up.railway.app` (экран «Сигналы» появится после деплоя консоли).

## Открытые вопросы
- **Следующему чату (главное):** code-review ветки → ⛔ merge в main (слово Оператора) → деплой Борса
  `SIGNAL_JOURNAL_ENABLED=1`+`SIGNAL_JOURNAL_CORE=BORS` (Борс первым, Куратор) + деплой ядра (миграция
  0016) + консоли → живая лента → сверка полноты N дней (приёмка Куратора).
- **Куратору (QUEUE):** финальный взгляд на диф ветки (опц.); **ADR-0024** (вариант C ведения:
  reanchor/trail/scalp через мини-дельту вендора) — будущий шаг после костяка.
- **Оператору:** следит за V3-пере-якорем на бирже (Борс+Персиваль); техдолг живой цены — потом.

## Следующий шаг
**Прогнать code-review ветки `task/s8-signal-journal`** → устранить находки → **⛔ merge в main**
(слово-подтверждение Оператора) → **деплой Борса** с `SIGNAL_JOURNAL_ENABLED=1` + ядра (миграция) +
консоли → убедиться, что события идут (экран «Сигналы») → **сверка полноты N дней** = приёмка №3.

## Проверка для нового чата
- [ ] `main @ 19d2bcc`, ветка `task/s8-signal-journal @ 0d99c53` (запушена, 4 впереди main, НЕ влита);
      незакоммиченного своего нет (iCloud-дубли `… 2.*` игнорировать).
- [ ] Тесты: картридж **252** + core **34** + журнал **13** (`bots/pifagor-cartridge/.venv/bin/pytest
      tests/test_signal_journal.py`); ruff картриджа + `../bots/pifagor-cartridge/.venv/bin/ruff check .`
      из core; tsc консоли (`cd console && npm ci && node_modules/.bin/tsc`) — чисты.
- [ ] Борс `cd8d0534` + Персиваль `a6df714f` живы на V3; стражи Галахад `dd7427a5` не тронут
      (`python3 orchestrator/rw_logs.py <id> 120`). Ядро healthz 200.
- [ ] Аксиома пере-якоря в `wiki/entities/pifagor-engine.md` + память `pifagor-reanchor-axiom.md`.
- [ ] QUEUE хвост: Куратор подписал №3 (d1 B+C/d3/d4 + вариант A + П1-П4 + guard); код готов на ветке.
- [ ] Порция №3 план `wiki/progress/s8-signal-journal.md` — под-шаги 1–5 `[x]`, под-шаг 6 (review→
      merge→деплой) `[ ]`.
- [ ] Секреты — только Railway env (RAILWAY_*, ключи Bybit demo, пароли postgres-*); не в git/лог/чат.
- [ ] Время: логи Railway/движок в UTC, Оператор в EEST (UTC+3) — при докладе КОНВЕРТИРУЙ UTC→EEST.
