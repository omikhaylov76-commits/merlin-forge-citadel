---
type: progress
title: MFC-005 — core-сторона Контракта Бота (шов S4): телеметрия + команды
tags: [progress, bot-contract, telemetry, commands, seam-s4, schema-first]
updated: 2026-07-11
sources: [concepts/bot-contract.md, concepts/seams.md, concepts/domain-model.md, decisions/0005]
---
# MFC-005 — core-сторона Контракта Бота (шов S4)

**Цель.** Реализовать приёмную сторону платформы для картриджа бота (шов S4, Контракт Бота v0):
push-телеметрия (heartbeat/equity/trades/events) + доставка команд (pause/resume/stop_close) через
API ядра, токеном инстанса. Schema-first: сначала JSON-схемы в `contracts/`, потом код по ним.
Картридж paper-bot, который это использует, — отдельная задача MFC-006.

**Границы (законы).** Токен инстанса видит ТОЛЬКО свой инстанс (SEC7). Свободные поля (detail/note/
symbol) — недоверенный ввод: храним параметризованно, экранируем на ВЫВОДЕ (не здесь). Телеметрия
идемпотентна (dedup). heartbeat кормит stale-скан MFC-003 (last_heartbeat_at). Команды — в audit_log
(закон №4). Секретов в v1 нет (paper). Long-poll команд НЕ держит коннект (SCL1, как jobs).

**Ветка:** `task/mfc-005`. **Режим:** автономный (протокол Куратора).

Последний коммит: 484a6fa

## Схема-first
- [x] 1. `contracts/*.schema.json` (v0): heartbeat, equity, trades[], events[], command-response ($id с v0).
       Тест: схемы валидны как JSON Schema + их examples проходят (jsonschema). Pydantic-синхро — шаг 4.

## Ядро — данные и auth
- [x] 2. Миграция 0004 + ORM (round-trip чист, 57 тестов): `equity_points`, `trades`, `events`,
       `commands`. Dedup-констрейнты (trades exec_id; equity ts; events ts+kind), индексы (instance,
       ts DESC), received_at авторитетно, equity Numeric (не float). commands: статусы + ix активных.
- [x] 3. Instance-token auth: `current_instance` (токен инстанса → свой Instance, SEC7). Выпуск instance-
       токена при создании инстанса + Контракт-env деплоя (MF_INSTANCE_ID/TOKEN, MF_CORE_URL). Тест env обновлён.

## Ядро — приём телеметрии (S4 →)
- [x] 4. `routes_telemetry.py`: heartbeat (→ last_heartbeat_at, кормит stale-скан) + equity/trades/events
       (ts-skew 422, dedup ON CONFLICT DO NOTHING, батч>500→413, currency=USDT). Pydantic=зеркало схем.
       13 тестов: dedup-идемпотентность, ts/currency/лимит, принципал 403 / чужой инстанс 404, sync схема↔модель.

## Ядро — команды (S4 ←)
- [ ] 5. GET `/v1/commands/next?wait=` (long-poll, липкий stop_close пока instance в stopping, OPS1) +
       POST `/v1/commands/{cmd_id}/ack` (ok→stopped при stop_close; error→не гасить). Продюсер оператора
       POST `/v1/instances/{id}/commands {kind}`. Аудит команд (закон №4). + тесты.

## Замыкание
- [ ] 6. Живой прогон: instance-токен → push heartbeat/equity/trades → stale-скан видит свежесть →
       enqueue pause → бот-эмуляция poll/ack. Вики (core-api/seams S4/domain-model/telemetry-schemas)
       + roadmap/log + code-review → merge в main (--no-ff) → QUEUE «готово к разбору».
