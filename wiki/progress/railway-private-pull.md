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
- [ ] 1. `railway.py`: +конфиг (environment_id/registry_username/registry_token); `deploy()` кладёт
        `registryCredentials` в serviceCreate при наличии токена; после create/adopt зовёт
        `serviceInstanceDeploy(serviceId, environmentId)`; environmentId резолвит рантайм (production).
- [ ] 2. `config.py` + `main.py`: поля ghcr_pull_username/ghcr_pull_token/railway_environment_id → в драйвер.
- [ ] 3. `test_railway_driver.py`: хендлер учит environments + serviceInstanceDeploy; тесты:
        креды в serviceCreate когда заданы / отсутствуют когда нет; serviceInstanceDeploy вызван после deploy.
- [ ] 4. pytest orchestrator зелёный; code-reviewer; ⛔ diff → merge в main.

## Границы
Секрет только в env (не в git/лог/чат). Образ приватный (Куратор #44). Реальная торговля — гейт go-live.
variableUpsert на adopt (обновление env существующего сервиса) — не сейчас, в QUEUE если понадобится.
