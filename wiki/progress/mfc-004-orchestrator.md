---
type: progress
title: MFC-004 — оркестратор + InfraDriver (jobs-транспорт по ADR-0009)
tags: [progress, orchestrator, infra-driver, jobs, seam-s3, seam-s5]
updated: 2026-07-11
sources: [decisions/0009-jobs-transport.md, concepts/seams.md, concepts/flows.md]
---
# MFC-004 — оркестратор + InfraDriver

**Цель.** Замкнуть контур деплоя платформы: ядро ставит jobs (deploy/teardown) в таблицу-контракт,
оркестратор арендует их через internal API ядра (long-poll+lease+fencing, ADR-0009) и исполняет через
абстрагированный **InfraDriver** (RailwayDriver v1 + DockerDriver-заглушка + FakeDriver для тестов/демо).
Живой прогон Railway API — отдельная веха roadmap («проверка допущения №3»), здесь НЕ гоняем боевой Railway.

**Границы (закон №3).** core и orchestrator — РАЗНЫЕ модули, друг друга не импортируют. Общение — только
HTTP (шов S3) + таблица-контракт `jobs` (владелец схемы — core). Секретов ключей биржи в v1 нет (paper-bot;
конверт-шифрование — Ф2). Развилок нет: механизм = ADR-0009, поверхность = швы S3/S5.

**Ветка:** `task/mfc-004`. **Режим:** автономный — стоп только на слиянии в main (необратимо).

Последний коммит: 2d1b6c9

## Ядро (core) — расширяем существующий модуль
- [ ] 1. Миграция 0003 `jobs` + ORM `Job`: kind(deploy/teardown, CHECK; backtest зарезервирован-отвергается),
       status(pending/leased/done/failed), attempts, lease_expires_at, lease_nonce (fencing), instance_id
       (ссылка без FK, ADR-0013), payload/result JSONB, партиал-уникальный «≤1 активный deploy на инстанс».
- [ ] 2. Internal jobs API (`/v1/internal/jobs/*`, скоуп `orchestrator`): `require_principal`;
       `GET next?wait=` — long-poll аренда (SELECT…FOR UPDATE SKIP LOCKED, БЕЗ удержания коннекта, SCL1);
       `POST {id}/ack` — fencing по lease_nonce, attempts, терминальные правила (deploy: 3 фейла→failed +
       teardown-компенсация OPS3; teardown: не терминален, бесконечный backoff OPS5), переходы status
       инстанса, аудит каждой аренды/ack (закон №4). + тесты.
- [ ] 3. Продюсеры (оператор): `POST /v1/instances` → instance(pending)+deploy-job; `POST /v1/instances/{id}/teardown`
       → teardown-job. Аудит обоих. + тесты.
- [ ] 4. CI: параметризовать/дополнить — джоба `core` уже гоняет новые тесты (Postgres есть). Проверить ruff.

## Оркестратор (orchestrator) — новый модуль
- [ ] 5. `InfraDriver` (ABC): deploy(image,env,name)→infra_ref · destroy(infra_ref) · status(infra_ref);
       формат infra_ref `railway:{project}:{svc}` (SCL8); `FakeDriver` (in-memory, тесты/демо);
       `DockerDriver` — NotImplemented-заглушка + conformance-тест (S5). pyproject + config.
- [ ] 6. `RailwayDriver` (GraphQL: serviceCreate/redeploy/delete; restartPolicy=never OPS1; destroy 404=успех
       OPS5). Боевой прогон — отдельная веха; здесь код структурно готов, юнит-тест на построение запросов.
- [ ] 7. `CoreClient` (httpx: next/ack) + `worker`-цикл (аренда→диспетч по kind→ack, fencing-nonce,
       backoff+jitter при отказе инфры, отпуск lease ≠ attempts++ OPS16). + тесты (httpx.MockTransport + FakeDriver).
- [ ] 8. CI: джоба `orchestrator` (ruff + pytest, без Postgres).

## Замыкание
- [ ] 9. Живой сквозной прогон: core (uvicorn) + `POST /v1/instances` (deploy-job) + worker с FakeDriver →
       job done, infra_ref проставлен, audit-строки. Хвост логов как доказательство.
- [ ] 10. Вики (G): core-api (ручки jobs/instances), seams (S3/S5 → реализовано), flows (сверить трассу деплоя),
       index/log, roadmap (MFC-004). + code-review → ⛔ слияние в main (слово-подтверждение).
