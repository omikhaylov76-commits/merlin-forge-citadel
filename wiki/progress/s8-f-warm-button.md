---
type: progress
title: S8 F-warm-button (ADR-0022) — «Поставить» валидный сетап по команде (добить Борса)
tags: [progress, s8, f-warm-button, warm-apply, adr-0022, contract, bors]
updated: 2026-07-22
---

# S8 · F-warm-button — постройка (ADR-0022)

Подписан Куратором (QUEUE 2026-07-22, вариант А, часть «добить Борса»). Цель: детерминированная
постановка валидного сетапа (вкл. reanchored PENDING) по кнопке Оператора → закрыть п.1/п.2 приёмки Борса
вживую (самоход/горн их не показывают — F-lookahead: годные с рынка не входят в узкий набор Борса).

## Ключ разведки: движковая часть УЖЕ ЕСТЬ (0-vendor)
Вендор `bots/pifagor/vendor/app/cycle.py`:
- `maybe_warm` (:336) — каждый 15m-тик читает durable-интент `WARM_APPLY` из config_log (поле `new` =
  одобренные монеты, CSV/JSON — `_parse_warm_approved` :303); safety-гейт (пауза/kill/equity) → дроп;
  иначе на каждую → `_warm_one_button`; single-shot по warm-ack (идемпотентно).
- `_warm_one_button` (:318) — ставит ВАЛИДНЫЙ PENDING (вкл. reanchored — назначение кнопки); `has_active`
  →skip, `kind!=PENDING` (OPEN)→skip, `_warm_cap_ok`→skip. Ставит `_warm_place` (существующий путь).

Это «кнопка Прогреть выбранные» (Веха 5.8 п.4b), НИКОГДА не прокинутая в консоль/Контракт. **Геном не трогаем.**

## Что строим (только проводка, 4 слоя)
1. **Ядро** `core/app/routes_dozor.py`: `POST /instances/{id}/scout/warm-apply` — `require_role("operator")`
   (портал НЕ видит, Закон 5) → `Command(kind="warm_apply", payload={coins})` + `write_audit("warm_apply_button")`.
   Body `WarmApplyBody{coins:[str]}`.
2. **Адаптер** `bot.py`: `cmd == "warm_apply"` → `_warm_apply(payload)` → `reader.warm_apply(coins)`; ack ok/error.
3. **Адаптер** `reader.py`: `warm_apply(coins)` → `config_log_append("WARM_APPLY", None, csv, source="button")`
   (зеркало `warm_now`→WARM_AUTO_NOW). Движок подхватит на след. 15m-тике.
4. **Консоль** `api.ts`: `warmApply(id, coins)` → POST. **Кнопка «Поставить»** по строке стека в
   `fleet/BotCard.tsx` (Оператор-only; движок сам валидирует — ставит только валидный PENDING, невалидные skip+log).
5. **Контракт/ADR-0022**: команда `warm_apply` (Оператор-only, портал не видит, RBAC/аудит как у прочих;
   прецедент PAUSE/STOP_CLOSE по духу — торговая, не критическая).
6. **Тесты vs НАСТОЯЩИЙ вендор** (урок S7): ставит reanchored PENDING; OPEN→skip; has_active→skip; cap; single-shot гасится.

## Условия подписи (Куратор, дословно)
Портал не видит · 0-vendor (интент→существующий maybe_warm; правка генома для проводки НЕ нужна, если
понадобится — СТОП+доклад) · single-shot+ack · тесты vs вендор · демо · Персиваль/Галахад не трогаем.

## Порядок
разведка ✓ → план ✓ → код (ядро+адаптер+консоль) → тесты vs вендор → code-review → merge → деплой Борса →
**живой показ: Оператор жмёт «Поставить» на живом валидном сетапе (1INCH/EPIC — reanchored сейчас в наборе
Борса) → Борс ставит демо-ордер → п.1/п.2 закрыты.** Это добивает эталон Борса. Разведка/Кузница — ПОСЛЕ.
