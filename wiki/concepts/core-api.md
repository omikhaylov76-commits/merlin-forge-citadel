---
type: concept
title: API ядра (core) — состояние MFC-004
tags: [core, api, auth, scheduler, instances, jobs, health]
updated: 2026-07-11
sources: [core/, decisions/0008, 0009, 0010, 0012, 0013]
---
# API ядра (core)

Реализовано в MFC-001 (скелет) + MFC-002 («часовой») + MFC-003 (instances + боевая свёртка) +
MFC-004 (jobs-транспорт + продюсеры). FastAPI app-factory (`create_app`), структурный JSON-лог с
request-id. Это состояние на сегодня; полный домен и швы — [domain-model](domain-model.md) / [seams](seams.md).

## Ручки
- `GET /healthz` — liveness (без БД) + блок `scheduler` (dead-man часового, ADR-0012).
- `GET /readyz` — readiness: БД доступна И миграции на head (иначе 503).
- `POST /v1/auth/login` {email, password} → {token, token_type} (пароль argon2; TOTP off, до go-live).
- `GET /v1/auth/me` — текущий пользователь (Bearer).
- `POST /v1/auth/logout` — отзыв токена (204).
- `GET /v1/admin/ping` — только роль operator (RBAC-демо).
- `GET /v1/users/{id}` — владение: свой профиль или operator; иначе 403 (SEC7).
- `POST /v1/instances` (operator) → instance(pending) + deploy-job. Railway НЕ зовётся напрямую
  (S1/S3): ядро ставит job, исполняет оркестратор. 409, если на счёте уже живой инстанс (OPS3).
- `POST /v1/instances/{id}/teardown` (operator) → teardown-job (идемпотентно; 409, если уже в очереди).
- `GET /v1/internal/jobs/next?wait=` (принципал `orchestrator`) — long-poll аренда job (204, если пусто).
- `POST /v1/internal/jobs/{id}/ack` (принципал `orchestrator`) — завершить: done|failed|release + fencing.

## Auth (ADR-0008v2)
Единый opaque-токен 256 бит; в БД хранится SHA-256 (не сам токен). Скользящий TTL 12ч, мгновенный
отзыв (`revoked_at`). Проверка владения — на ВСЕХ ручках. Пароль — argon2 (только человек).

## Данные (миграции, Alembic — единственный путь к схеме, закон №7)
- 0001: `users` (role строка+CHECK, `email` уникальный), `api_tokens` (хэш SHA-256),
  `audit_log` (+триггер append-only).
- 0002: `instances` (status=намерение, health=свежесть, `last_heartbeat_at`; FK отложены — ADR-0013;
  партиал-индекс «≤1 живой инстанс/счёт», OPS3/MON2).
- 0003: `jobs` (kind deploy/teardown+CHECK, status, attempts, lease + `lease_nonce` fencing, payload;
  FK на `instances`; партиал-индекс «≤1 активный deploy/инстанс», OPS2; `backtest` зарезервирован — CHECK не пускает).

## Наблюдаемость
request-id на каждый запрос (заголовок `X-Request-ID` + строки лога) для сшивки с audit_log.
Каждое действие оператора/клиента — строка `audit_log` (закон №4); секреты не логируются (закон №2).

## Часовой (core-scheduler, MFC-002/003)
Один asyncio-цикл в процессе ядра (`app/scheduler.py`, на `app.state`): каждый оборот исполняет
дозревшие свёртки и штампует монотонный тик. `/healthz` отдаёт блок `scheduler`:
`state` = `stopped|running|dead`, `tick_age_s`, число свёрток. Dead-man: `dead`, если тик застыл
дольше 3× периода (`scheduler_tick_seconds`, дефолт 60с). Вариант A (ADR-0012): верхний `status`
/healthz не гейтит — смерть цикла видна в теле, реакция через алерт (SCL3), не авто-рестарт.
**Первая боевая свёртка (MFC-003) — stale-скан health инстансов** (`app/instance_health.py`): по
свежести `last_heartbeat_at` ставит `health` ok→stale→dead (пороги в config), переход — строка
`audit_log` (`actor=system:sentinel`); без действий над инстансом (seams:62), доставка алерта —
с outbox позже. Свёртка идёт через `to_thread` (БД-сессия не блокирует цикл, SCL1); её падение
изолировано (сосед не роняет часового).

## Jobs-транспорт (MFC-004, шов S3, ADR-0009)
Ядро — единственный писатель `jobs`; оркестратор арендует через internal API (таблицу не читает,
закон №3). Аренда (`app/jobs.py`): `lease_next` берёт старейший pending через `FOR UPDATE SKIP
LOCKED` (single-claim) + реклеймит протухшие аренды (attempts++). `ack` fencing по `lease_nonce`
(OPS2): deploy 3 неудачи → failed + instance=failed_deploy + teardown-компенсация (OPS3); teardown
вечно requeue (OPS5); release без штрафа attempts (инфра лежит, OPS16). Аренда/ack двигают статус
инстанса (pending→deploying→starting; →stopping→stopped). **SCL1: long-poll `/next` не держит
коннект** — своя короткая auth-сессия + опрос короткими сессиями со сном без коннекта.

## Запуск (dev) / тесты
`docker compose -f infra/docker-compose.dev.yml up -d --wait` → в `core/`: `alembic upgrade head` ·
`uvicorn app.main:app` · `pytest` (нужен `DATABASE_URL`). CI: `.github/workflows/ci.yml`
(ruff+pytest на свежем Postgres — гейт §2).
⚠️ macOS: если `import psycopg`/`argon2` висит — `xattr -dr com.apple.quarantine .venv` (Gatekeeper).

## Ещё нет (следующие шаги)
outbox-алерты (доставка stale/dead Оператору); paper-bot по Контракту Бота (S4 push-телеметрия);
боевая обкатка Railway API (RailwayDriver структурно готов, схема GraphQL — на живом инстансе);
остальной домен clients/telemetry/billing (свои миграции); биржевые ключи (Ф2); биллинг HWM (Ф3).
