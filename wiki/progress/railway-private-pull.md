---
type: progress
title: RailwayDriver — приватный pull + запуск образа (#46 з.2 enable)
tags: [orchestrator, railway, ghcr, deploy, f2]
updated: 2026-07-15
sources: [_curator/DIRECTIVES.md#46, wiki/handoffs/HANDOFF_2026-07-12_session_5.md]
---
# progress: RailwayDriver — registryCredentials + serviceInstanceDeploy (#46 з.2)

Цель: чтобы оркестратор реально деплоил картридж Персиваля из ПРИВАТНОГО ghcr-образа в облаке.
Два пробела драйвера (с.5): (1) `serviceCreate` не передаёт registry-креды → приватный образ не тянется;
(2) `serviceInstanceDeploy` (запуск образа) не вызывается → сервис создаётся пустым, не деплоится.

Секрет (PAT read:packages) — в `orchestrator/.env` (gitignored, как RAILWAY_API_TOKEN); в код/лог/git не попадает.

Последний коммит (ветка task/railway-private-pull от): 2094313

## План (под-шаги)
- [x] 1. `railway.py` (39db511): registryCredentials в serviceCreate при токене; serviceInstanceDeploy
        после create/adopt; environmentId из конфига или резолв production.
- [x] 2. `config.py` + `main.py` (39db511): ghcr_pull_username/ghcr_pull_token/railway_environment_id → драйвер.
- [x] 3. `test_railway_driver.py` (39db511): +5 тестов (креды есть/нет, образ запущен после create и adopt,
        env из конфига без лишнего запроса). ruff clean, **28 passed**.
- [x] 4. Код доказан на unit (MockTransport). ЖИВАЯ проверка формы (Railway принял registryCredentials +
        serviceInstanceDeploy) подтверждена на з.2 (деплой Персиваля). Влит в main (d9a0531).

## Статус
Ветка готова, ждёт PAT Оператора (orchestrator/.env `GHCR_PULL_TOKEN=`). Как впишет → з.2: DRIVER=railway,
деплой Персиваля картриджем в облако (dry-run) → если Railway принял форму живьём → code-reviewer → merge.

## Границы
Секрет только в env (не в git/лог/чат). Образ приватный (Куратор #44). Реальная торговля — гейт go-live.
variableUpsert на adopt (обновление env существующего сервиса) — не сейчас, в QUEUE если понадобится.
