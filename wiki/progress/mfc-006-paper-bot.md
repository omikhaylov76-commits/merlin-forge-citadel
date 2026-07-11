---
type: progress
title: MFC-006 — картридж paper-bot (эталонная реализация Контракта Бота v0)
tags: [progress, paper-bot, bot-contract, seam-s4, cartridge]
updated: 2026-07-11
sources: [concepts/bot-contract.md, contracts/, _curator/DIRECTIVES.md (разбор #4)]
---
# MFC-006 — картридж paper-bot

**Цель.** Первый картридж — ЭТАЛОННАЯ реализация Контракта Бота v0 (по нему потом лепится обёртка
Пифагора и будущие движки). Фейковый бот: equity-синус, seeded «сделки», ЧЕСТНЫЕ семантики ADR-0005
(pause = стоп новых входов, позиции держатся; stop_close = закрыть и встать). К бирже не ходит
(paper-only, без ключей). Клиент API S4 (шов S4, наоборот от MFC-005). Обкатывает конвейер вживую.

**Указания Куратора (разбор #4).** Чисто и задокументированно (README: как картридж реализует Контракт),
минимум зависимостей (httpx). Детерминизм (синус + сид, тесты воспроизводимы). Сквозняк ВСЕГО контура:
heartbeat→часовой видит живость/флипает health; телеметрия; pause и stop_close честными семантиками.

**Границы.** paper-only. Ring-буфер при недоступности core — best-effort в v1 (полный кольцевой ~24ч —
отложить, Контракт). Модуль отдельный (bots/paper-bot), ядро/оркестратор не импортирует.

**Ветка:** `task/mfc-006`. **Режим:** автономный (протокол Куратора).

Последний коммит: 27103a1

- [x] 1. Скелет: pyproject (httpx; dev pytest/ruff/jsonschema) + config.py (env Контракта MF_*) +
       README (как картридж реализует Контракт) + пакет.
- [x] 2. `engine.py` PaperEngine: детерминированный синус + seeded сделки, running/paused/stopping/
       stopped, позиция. Честно: pause=нет новых входов (позиции держатся), stop_close=закрыть+kill_switch+
       встать. 7 тестов: детерминизм, pause держит позицию, stop_close закрывает, payload'ы валидны по схемам.
- [x] 3. `client.py` CoreClient (httpx): push heartbeat/equity/trades/events + commands next/ack.
       5 тестов (MockTransport). Ошибки не глотает — best-effort решает цикл.
- [x] 4. `bot.py` + `main.py` — цикл: heartbeat ≤60с (троттлинг) + tick-телеметрия + честное исполнение
       команд (pause держит, resume, stop_close→закрыть+доложить+ack ok+встать; unknown→error). best-effort
       к сбоям. 7 тестов (FakeClient).
- [x] 5. CI: джоба `paper-bot` (ruff+pytest, без Postgres) добавлена.
- [ ] 6. Живой сквозняк: instance из ядра → paper-bot процессом → heartbeat/health, телеметрия копится,
       pause (позиции держатся) и stop_close (закрыл+встал) честно. Вики (README/seams/entities) +
       roadmap/log + code-review → merge в main (--no-ff) + push → QUEUE «готово к разбору».
