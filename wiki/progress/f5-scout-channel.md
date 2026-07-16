---
type: progress
title: Ф5 Разведка — scout-канал (дуга #50–#53) → Кузница
tags: [phase5, scout, contract, adr, schema, roadmap]
updated: 2026-07-16
---
# Ф5 Разведка · scout-канал (дуга #49–#53)

Цель дуги: довести живые сетапы скаута Пифагора до консоли (граф сетапа + сортировка), не заставляя
платформу сканировать рынок — она ПРИНИМАЕТ снимки от бота (ADR-0016 «Разведчик на борту, исправленный»).
Единица работы — директива #NN Куратора; каждый шаг — по одному, после приёмки предыдущего.

Последний коммит: 1d7e91c

## #49 — Рекон (данные сканера) — ГОТОВО (отчёт в QUEUE, 2026-07-16)
- [x] Экран Разведки в консоли (фикстура) + поля скаута КАК ЕСТЬ + канал данных + данные графика — сверены кодом.

## #50 — ADR-0016 + scout-канал Контракта v1 (ТОЛЬКО документы+схема+тесты, 0 строк в vendor/)
- [x] 1. ADR-0016 `wiki/decisions/0016-scout-channel-onboard-scout.md` — (а)–(д)
- [x] 2. Схема `contracts/telemetry-scout.schema.json` — replace-снимок per (instance,symbol,tf)
- [x] 3. Бамп Контракта v0→v1: $id/title 5 схем + CONTRACT_VERSION оба картриджа + стале-лынт доков
- [x] 4. Sync-гвозди оба картриджа (`tests/test_contract_version.py`): версия-синк + структурный гвоздь полей (pifagor)
- [x] 5. Зелёные тесты: paper-bot 23 · pifagor 73 · core 11 (схемы + schema↔Pydantic)
- [x] 6. Само-ревью (workflow 4 линзы) — красных нет; yellow-дельта внесена
- [x] 7. Приёмка Куратора построчно ✓ (развилка «Pydantic-зеркало» → #52 подписана) → merged в main (feat 74048a5 + fix ruff 1d7e91c), **CI зелёный = финал #50**.
  Разъезд «партитуры» (roadmap/progress/PROTOCOL) синхронизирован в этом же шаге (#50 ДОПОЛНЕНИЕ, принято).

**#50 ЗАКРЫТ (2026-07-16).** Стоп — жду директиву #51 (изоляция картриджа), сам не начинаю.

## #51 — Изоляция картриджа (В РАБОТЕ, доказано локально)
Последний коммит: c3f9c25 · механика в обёртке, 0 строк в vendor/, в облако НЕ катить, скаут на флоте НЕ включать.
- [x] fail-closed `SCOUT_ENABLED`-гейт в start.sh (vendor-дефолт True не решает; проверено (а))
- [x] отдельная `scout.db` через `DB_PATH` (env только дочернему скауту, не адаптеру; db.py:365 / ADR-0016 в.2; (б))
- [x] супервизор скаута в start.sh (liveness heartbeat + RSS-кап, рестарт только скаута) → `app/scout_health.py` (в)(г)
- [x] разведение бёрстов (SCOUT_RPS=1 / SCOUT_LIST_MAX=50 / SCOUT_CAL_UTC_HOUR / SCOUT_TFS) — env обёртки (в.5)
- [x] хвост A #48: динамический баннер по $LIVE_TRADING_ENABLED (dry-run ↔ LIVE demo)
- [x] доказательства (а)-(г) локальным dry-run (fake-scout, реальный start.sh через source-guard) + тесты 89 ✅
- [x] приёмка Куратора построчно ✓ (супервизор-трактовка + DATABASE_URL подписаны); merged f9988d6, CI зелёный
  🔶 DATABASE_URL → #52: скаут всегда на своей SQLite (зачистка DATABASE_URL дочернему скауту) + правка ADR-0016 в.2.

**#51 ЗАКРЫТ (2026-07-16).** Стоп — жду директиву #52 (труба целиком: ручка ядра + таблица/миграция 0009 + readout + адаптер scout_reader/mapper/push + сквозняк локально). Сам не начинаю. В облако не катим.

## #52 — Труба целиком (В РАБОТЕ)
Последний коммит: f9d3a94 · ядро+readout+адаптер+сквозняк локально. 0 vendor, консоль #53, SCOUT_ENABLED не выставлять, в облако не катить.
- [~] Ядро: ручка `POST /v1/telemetry/scout` (principal instance, SEC7) + Pydantic-зеркало `ScoutSnapshotIn` (полное, все required вкл. data_upto) + replace-семантика (upsert (instance,symbol,tf) + удаление выпавших) + капы 413
- [~] Миграция 0009 `scout_snapshots` (down_revision 0008_billing_lifecycle)
- [~] Readout `GET /v1/instances/{id}/scout` (require_role operator)
- [~] Адаптер: `scout_reader.py` (DB owner=False db_path=scout.db, триггер по scan_ts) + `mapper.py` (снимок+orders/position+config_mismatch 4 крутилки+detector_version/fingerprint/producer) + push в bot.py
- [~] Хвост #51: зачистка DATABASE_URL дочернему скауту + правка ADR-0016 в.2
- [x] Core sync-тест: ScoutSnapshotIn == схема (extra=forbid ловит дрейф, вкл. data_upto) + required-parity
- [x] сквозняк локально: fake-scout→scout_reader→mapper→push→ядро→readout; replace (WIFUSDT исчез)/идемпотентность доказаны; 413/зеркало в core-тестах. Локальный Postgres (homebrew, не docker).
- [x] само-ревью (workflow 3 линзы): 1 RED (триггер по scout_meta вместо scout_control — умершие сетапы висели бы до утра) ИСПРАВЛЕН + yellow-дельта. Тесты: core 32, cartridge 102, paper-bot 23.
- [x] коммит fa3f1b5 → **CI зелёный (7/7 джоб) = финал #52**; отчёт Куратору построчно в QUEUE

**#52 ЗАКРЫТ (2026-07-16).** Данные едут: scout → адаптер → ядро → readout. Дальше — #53 (консоль-график Разведки, levels-only Фаза 1). Стоп — жду директиву #53. В облако не катим, SCOUT_ENABLED на флоте не выставляем.

**Форвард-риск #53 (зафиксировать при приёмке #53):** адаптер Фазы 1 НЕ шлёт klines (у скаута нет 15m/5m; ADR-0016 д). #53-график = **levels-only** (A→B + Fib + стоп линиями, без свечного фона) пока апстрим pifagor-v81 не отдаст младший ТФ. Живая верность orders/position — гейт go-live (в dry-run пусто).

## #53 — Консоль-график сетапа (ещё НЕ начат)
- [ ] живой экран Разведки: свечи (klines_tf) + A→B + Fib-ноги 0.382/0.5/0.618 + стоп, вместо фикстур
- [ ] сортировка/статусы forming/tracking/ready; подпись «уровни от скаута X» в режиме представителя

Далее — Кузница (библиотека профилей + паспорта OOS + залок эталона).
