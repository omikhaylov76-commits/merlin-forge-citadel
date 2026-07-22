---
type: decision
title: ADR-0022 — F-warm-button — команда Контракта warm_apply («Поставить» валидный сетап)
tags: [adr, contract, command, f-warm-button, warm-apply, s8, dinamo-bliznec, bors, law5, rbac]
updated: 2026-07-22
sources: [_curator/QUEUE.md, wiki/progress/s8-f-warm-button.md, wiki/decisions/0021-warm-rhythm-socket-genome.md]
---
# ADR-0022 — F-warm-button: команда Контракта `warm_apply`

## Контекст
Самоход/горн (ADR-0021) ставят ТОЛЬКО `auto_eligible` (нетронутый PENDING). Валидные, но пере-якоренные
(`reanchored`) сетапы — вендор признаёт их безопасными для человека (`_warm_one_button`, cycle.py:318), но
авто-путь их не берёт. Плюс **F-lookahead** (доказано вживую 2026-07-22): годные сетапы на рынке есть
(CBRS/BEAT/UB/ZBT auto + ENA/EPIC/1INCH/… reanchored), но узкий динамический набор Борса их системно не
включает → самоход/горн `поставлено 0`. Итог: **эталон Борс безопасен, но не может ПОКАЗАТЬ живой заход**
(п.1/п.2 приёмки Куратора недоказуемы) — нет детерминированной постановки по требованию.

## Решение (подписано Куратором, QUEUE 2026-07-22, вариант А — часть «добить Борса»)
Новая **команда Контракта `warm_apply`** — «Поставить» валидный сетап (вкл. reanchored) по клику Оператора.
Движковая часть УЖЕ существует (0-vendor): вендор `maybe_warm`→`_warm_one_button` — «кнопка Прогреть
выбранные» (Веха 5.8), никогда не прокинутая в Контракт/консоль. **Геном НЕ трогаем** (манифест дельт
неизменен — 2 дельты ADR-0019/0021; вендор `bots/pifagor/vendor` без правок).

### Проводка (4 слоя, 0-vendor)
1. **Ядро** `POST /v1/instances/{id}/scout/warm-apply` (`routes_dozor.py`) — `require_role("operator")` →
   `Command(kind="warm_apply", payload={coins})` + `write_audit("warm_apply_button")`. Body `{coins:[str]}`.
2. **Адаптер** `bot.py`: `cmd == "warm_apply"` → `reader.warm_apply(coins)` → `config_log_append("WARM_APPLY",
   None, csv, source="button")`. Движок подхватит на след. 15m-тике.
3. **Движок** (вендор, БЕЗ изменений): `maybe_warm` читает WARM_APPLY → `_warm_one_button` ставит валидный
   PENDING (вкл. reanchored); `has_active`→skip, `OPEN`→skip, cap→skip; single-shot по warm-ack.
4. **Консоль** `BotCard.tsx`: кнопка «Поставить» по строке стека (Оператор-only). Движок сам валидирует.

## Границы (условия подписи Куратора)
- **Портал клиента команду НЕ видит (Закон 5)** — Оператор-only (`require_role("operator")`; client → 403).
  Прецедент PAUSE/STOP_CLOSE по духу, но **торговая, не критическая** команда. Аудит как у прочих.
- **0-vendor** — интент в config_log → существующий `maybe_warm`. Правки генома для проводки НЕ потребовалось.
- **Single-shot + ack** — разовая постановка по клику, не ретрай (как WARM_APPLY/Веха 5.8).
- **Демо.** Персиваль/Галахад не трогаем. LIVE Борса уже открыт (Веха 2) — кнопка ставит демо-ордера.

## Тесты (vs НАСТОЯЩИЙ вендор — урок S7)
`tests/_warm_apply_vendor.py` (subprocess app==vendor): `_parse_warm_approved` CSV/JSON; `_warm_one_button`
СТАВИТ reanchored PENDING (суть кнопки, в отличие от `_warm_one`); OPEN→skip; has_active→skip; cap держит;
`maybe_warm` single-shot (ack гасит). `tests/test_warm_apply.py`: адаптер `reader.warm_apply` пишет CSV-интент.
`core/tests/test_dozor.py`: маршрут — команда+нормализация, 422 на пусто, **403 порталу** (RBAC).

## Последствия
- Борс становится ПОЛНЫМ образцом: Оператор жмёт «Поставить» на живом валидном сетапе → демо-ордер → п.1/п.2
  приёмки закрыты. Разведка/Кузница — по-прежнему в ожидании ПОСЛЕ (порядок Куратора).
- НЕ решает F-lookahead (узкий набор движка) — это отдельный, более глубокий вопрос (геном/динамика), отложен.
- Единая Разведка (правда движка per-coin) даст кнопке точную витрину «нужна кнопка»; сейчас кнопка по всей
  строке стека, движок валидирует (невалидную молча skip). Приемлемо для эталона; уточнится с Разведкой.
