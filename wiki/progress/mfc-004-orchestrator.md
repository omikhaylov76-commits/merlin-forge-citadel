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
- [x] 1. Миграция 0003 `jobs` + ORM `Job` (a1cd1a5): kind(deploy/teardown, CHECK; backtest зарезервирован-отвергается),
       status(pending/leased/done/failed), attempts, lease_expires_at, lease_nonce (fencing), instance_id
       (ссылка без FK, ADR-0013), payload/result JSONB, партиал-уникальный «≤1 активный deploy на инстанс».
- [x] 2. Internal jobs API (935e53b) (`/v1/internal/jobs/*`, скоуп `orchestrator`): `require_principal`;
       `GET next?wait=` — long-poll аренда (SELECT…FOR UPDATE SKIP LOCKED, БЕЗ удержания коннекта, SCL1);
       `POST {id}/ack` — fencing по lease_nonce, attempts, терминальные правила (deploy: 3 фейла→failed +
       teardown-компенсация OPS3; teardown: не терминален, бесконечный backoff OPS5), переходы status
       инстанса, аудит каждой аренды/ack (закон №4). + тесты.
- [x] 3. Продюсеры (f292e43) (оператор): `POST /v1/instances` → instance(pending)+deploy-job; `/teardown`
       → teardown-job. Аудит обоих. + тесты.
- [x] 4. CI: джоба `core` уже гоняет новые тесты (Postgres есть) — правок не нужно; ruff clean. (в f292e43)

## Оркестратор (orchestrator) — новый модуль
- [x] 5. `InfraDriver` (0bb52ae) (ABC): deploy(spec)→infra_ref · destroy · status; формат infra_ref
       `railway:{project}:{svc}` (SCL8); `FakeDriver` (in-memory, тесты/демо); `DockerDriver` —
       NotImplemented-заглушка + conformance-тест (S5). pyproject + config.
- [x] 6. `RailwayDriver` (1adabb6) (GraphQL усынови-или-создай/destroy идемпотентно). Боевой прогон —
       отдельная веха; код структурно готов + HTTP-механика под httpx.MockTransport (⚠️ схема — на обкатке).
- [x] 7. `CoreClient` (httpx: next/ack) + `worker` (аренда→диспетч по kind→ack, fencing-nonce,
       release при отказе инфры OPS16, backoff при недоступном ядре) + main. + тесты (MockTransport + FakeDriver).
- [x] 8. CI: джоба `orchestrator` (ruff + pytest, без Postgres) добавлена.

## Замыкание
- [x] 9. Живой сквозной прогон (uvicorn core + HTTP): deploy — instance pending→deploying→starting,
       infra_ref=railway:fake:mfc-inst-…, job done; teardown — →stopping→stopped, infra_ref очищен,
       обе job done, аудит цепочки (instance_created→deploy_enqueued→job_leased→job_ack ×2). ✅
- [x] 10. Вики (G) обновлена; независимое ревью пройдено (блокер ack + 3 nit закрыты); MFC-004 слит в
       main (ed18bb9, --no-ff), ветка удалена; roadmap/log merged:yes. Отложено в QUEUE: OPS13, аудит отказов.

**ЗАКРЫТО. Merged: yes (main ed18bb9). Следующее по маршруту — paper-bot по Контракту Бота v0.**
