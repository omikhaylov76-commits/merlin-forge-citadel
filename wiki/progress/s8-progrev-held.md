---
type: progress
title: S8 порция №2 — прогрев held (boot-шаг: coins.json из held ДО старта движка)
tags: [progress, s8, progrev-held, dynamic-universe, boot, prewarm, adr-0019]
updated: 2026-07-23
---

# Порция №2: прогрев held — ПЛАН v2 (ИСПРАВЛЕН после разведки; подход-класс подписан Куратором в каноне)

## Находка разведки (почему план v1 «правка tick» НЕ работал)
Движок читает `coins.json` ТОЛЬКО на старте (ADR-0019: не hot-reload). На редеплое:
1. Движок стартует ПЕРВЫМ (`start.sh:187` `engine_supervise &`), адаптер — позже (`:193`) → движок
   читает `coins.json` РАНЬШЕ, чем адаптерный `tick` его напишет → поднимается на дефолте-16.
2. Прогрев в `tick` пишет `gen="0"` (скана нет) = дефолтному `_egen="0"` супервизора → смены НЕ видит,
   рестарта нет (`start.sh:50`).
3. Даже с рестартом — при открытых позициях он ОТКЛАДЫВАЕТСЯ (`start.sh:53-58`, F-restart «а») — ровно
   целевой случай.
⇒ «правка `tick`» записала бы held, но движок бы его не подхватил. **Правильное место прогрева — ДО старта движка.**

## Дизайн v2 (0-vendor; boot-шаг + чистый писатель)
**boot-шаг `python -m app.prewarm_held` в `start.sh` ДО `engine_supervise &`** (ветка DYNAMIC_ENABLED=1):
- Читает held БЕЗ лока движка: `PifagorReader(owner=False)` (`reader.py:5` — «singleton-lock НЕ берём») →
  `snapshot()`=build_monitor → `mapper.held_symbols` (позиции size≠0 ∪ pending-ордера, из персистентной
  Postgres Борса). Best-effort: сбой/таймаут → боот продолжается (движок на дефолте, как раньше).
- Пишет `coins.json` из held с ДЕФОЛТ-барами (`coin_block()`; per-coin mb приедут со сканом) + `gen=0`
  атомарно. ПОЛ-НА-ПУСТОТУ: held пуст → не пишем (движок на дефолте — регресс нулевой).
- Движок стартует и читает `coins.json`=held → **ведёт позиции с 1-й минуты**, без рестарта/отсрочки.
- Первый реальный скан (scan_ms≠0) позже перезапишет вселенную per-coin (обычный путь, gen сменится → рестарт).

**`tick` НЕ трогаем** (меньше регресса). Провайдерный `_write_atomic` рефакторю в общий модульный
`_write_coins_atomic(path, coins, gen)` (тот же байт-в-байт) — переиспользует прогрев.

## Файлы
- `bots/pifagor-cartridge/app/dynamic_universe.py` — `_write_coins_atomic` (модульный, из `_write_atomic`) +
  `prewarm_coins_from_held(path, held) -> int`.
- `bots/pifagor-cartridge/app/prewarm_held.py` (новый) — entrypoint `python -m app.prewarm_held`:
  from_env → PifagorReader(owner=False) → held_symbols → prewarm_coins_from_held. Best-effort.
- `bots/pifagor-cartridge/start.sh` — в ветке DYNAMIC_ENABLED=1, ДО `engine_supervise &`:
  `timeout 20 python -m app.prewarm_held || echo "…пропуск"`.
- `bots/pifagor-cartridge/tests/test_prewarm_held.py` (новый) — vs НАСТОЯЩИЙ вендор.

## Тесты (vs НАСТОЯЩИЙ вендор + юнит)
- held непуст → coins.json содержит held (дефолт-бары), возвращает N; **грузится реальным
  `config.strategy._load_coins_config` / проходит `config.validate`** (движок примет).
- held пуст → 0, файл НЕ пишется (пол-на-пустоту).
- `_write_coins_atomic` регресс: провайдерный `_write_atomic` даёт БАЙТ-В-БАЙТ прежний coins.json/.gen
  (существующие per-coin/scout тесты зелёные).
- `prewarm_held.main` при DYNAMIC_ENABLED=0 → 0, ничего не пишет (флот/paper не задет).

## Инварианты
- 0-vendor (читаем вендор read-only owner=False; пишем только адаптерный coins.json; страж-дрейфа=3, без изменений).
- Персиваль/Галахад не трогаем (DYNAMIC выкл → boot-шаг no-op). 🔒 Демо.
- Полный персист scout.db (окно для бота БЕЗ позиций) — отдельный техдолг, НЕ здесь.
- ⚠️ Отклонение от плана v1 (подписан «правка tick») → ФЛАГ Куратору в QUEUE (его домен: подпись подхода).

## Порядок
план v2 → ветка → код (dynamic_universe helper+prewarm, app/prewarm_held, start.sh) → тесты vs вендор →
ruff/страж-дрейфа → code-review → ⛔ merge → образ :main → деплой Борса → живая сверка (редеплой с held →
coins.json с held с 1-й минуты, движок ведёт позиции сразу) → флаг Куратору.

## SHA
- (заполнить при merge)
