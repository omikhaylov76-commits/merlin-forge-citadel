---
type: runbook
title: Деплой картриджа Пифагора на Railway (облачная сборка, безопасный режим)
tags: [runbook, railway, pifagor, cartridge, deploy, gate]
updated: 2026-07-12
sources: [decisions/0003-railway-first.md, orchestrator/app/infra/railway.py, bots/pifagor-cartridge/README.md, _curator/DIRECTIVES.md]
---
# Деплой картриджа Пифагора на Railway

Образ картриджа собирается в ОБЛАКЕ (CI, #12) и лежит в ghcr; Railway тянет его по image-ref
(`RailwayDriver.deploy` → `serviceCreate(source.image)`). Локальный Docker не используем.

## Образ (ghcr, из CI на push в main)
- `ghcr.io/omikhaylov76-commits/mfc-pifagor-cartridge:main` (движется с main)
- `ghcr.io/omikhaylov76-commits/mfc-pifagor-cartridge:sha-4ef05ab` (иммутабельный пин merge-коммита)

## ⛔ ГЕЙТ ОПЕРАТОРА (что Инженер автономно НЕ делает)
1. **Доступ Railway к ghcr-пакету.** Пакет приватный по умолчанию. Либо сделать его **public**
   (github.com → Packages → `mfc-pifagor-cartridge` → Package settings → Change visibility → Public),
   либо дать Railway **registry-credential** (GitHub PAT со `read:packages`) в настройках сервиса.
   Без этого Railway не стянет образ (image pull error). *Инженер не меняет visibility — это право доступа.*
2. **Demo-ключи Bybit (НЕ боевые).** Для БУТА воркера Пифагора (`config.validate` требует
   `BYBIT_API_KEY`/`BYBIT_API_SECRET`). Оператор кладёт их в env Railway-СЕРВИСА (не в core, не в git —
   как RAILWAY_API_TOKEN). Безопасный режим НАТИВЕН: `LIVE_TRADING_ENABLED=0` (dry-run) + `BYBIT_DEMO=1`
   — дефолты образа. Без ключей контейнер идёт в адаптер-only (воркер не бутится). Реальные ключи/торговля
   = ОТДЕЛЬНЫЙ гейт go-live.
3. **Согласие на compute** (Railway Pro НЕ включаем, D2).

`RAILWAY_API_TOKEN`/`RAILWAY_PROJECT_ID`/`DRIVER` уже в `orchestrator/.env` (Оператор).

## Шаги (когда ghcr доступен)
1. Поднять core + orchestrator (`DRIVER=railway`, живой токен/проект из .env).
2. `POST /v1/instances` (operator-токен) с `image = ghcr…:sha-4ef05ab`, `env` = только MF_* (без ключей) →
   deploy-job; orchestrator арендует → `RailwayDriver.deploy` на живой Railway → сервис `mfc-inst-{id}`
   тянет образ и стартует.
3. Проверить: Railway ЗАПУСТИЛ контейнер (build/runtime-логи Railway — наш `start.sh` → адаптер;
   без ключей — «BYBIT_* не заданы → адаптер-only»). Это доказывает облачный деплой картриджа.
4. **Полный demo-режим:** Оператор добавляет demo-ключи в env сервиса `mfc-inst-{id}` (Railway) → redeploy →
   `start.sh` бутит воркер (dry-run demo) + адаптер. Ключи живут ТОЛЬКО в env Railway, не в core/git.
5. **Сквозняк demo (телеметрия):** требует, чтобы `MF_CORE_URL` был ПУБЛИЧНО достижим из Railway (core
   задеплоен/протуннелен). С локальным core будет ConnectError (как в обкатке paper-bot) — контейнер жив,
   но телеметрия не долетит. Полный телеметрический сквозняк = отдельный шаг (публичный core).
6. Прибрать по завершении демо: `destroy` сервиса (идемпотентно), чтобы compute не капал.

## Что уже доказано (до облака)
- Адаптер по Контракту: 70 тестов + parity(реальный build_monitor) + schema-conformance; независимое ревью.
- **ЛОКАЛЬНЫЙ живой сквозняк против реального ядра** (uvicorn+dev-БД): heartbeat/equity/trades/events
  приняты (health=ok), pause→PAUSE_ENABLED, stop_close→killswitch — весь контур S4 (см. log 2026-07-12).
- Облачная сборка образа CI→ghcr (джоба `cartridge-image`), smoke-импорт в образе зелёный.
- RailwayDriver GraphQL подтверждён на живом API (обкатка paper-bot, `railway-shakedown.md`).

## Итог
Технически картридж готов к облачному деплою. Остаётся действие Оператора (ghcr-доступ + demo-ключи).
Дальше по ПОРЯДКУ Куратора — «Малыш Мерлин» (#11).
