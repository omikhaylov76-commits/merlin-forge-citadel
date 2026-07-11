---
type: concept
title: API ядра (core) — состояние MFC-003
tags: [core, api, auth, scheduler, instances, health]
updated: 2026-07-11
sources: [core/, decisions/0008, 0009, 0010, 0012, 0013]
---
# API ядра (core)

Реализовано в MFC-001 (скелет) + MFC-002 («часовой») + MFC-003 (instances + боевая свёртка).
FastAPI app-factory (`create_app`), структурный JSON-лог с request-id. Это состояние на сегодня;
полный домен и швы — [domain-model](domain-model.md) / [seams](seams.md).

## Ручки
- `GET /healthz` — liveness (без БД) + блок `scheduler` (dead-man часового, ADR-0012).
- `GET /readyz` — readiness: БД доступна И миграции на head (иначе 503).
- `POST /v1/auth/login` {email, password} → {token, token_type} (пароль argon2; TOTP off, до go-live).
- `GET /v1/auth/me` — текущий пользователь (Bearer).
- `POST /v1/auth/logout` — отзыв токена (204).
- `GET /v1/admin/ping` — только роль operator (RBAC-демо).
- `GET /v1/users/{id}` — владение: свой профиль или operator; иначе 403 (SEC7).

## Auth (ADR-0008v2)
Единый opaque-токен 256 бит; в БД хранится SHA-256 (не сам токен). Скользящий TTL 12ч, мгновенный
отзыв (`revoked_at`). Проверка владения — на ВСЕХ ручках. Пароль — argon2 (только человек).

## Данные (миграции, Alembic — единственный путь к схеме, закон №7)
- 0001: `users` (role строка+CHECK, `email` уникальный), `api_tokens` (хэш SHA-256),
  `audit_log` (+триггер append-only).
- 0002: `instances` (status=намерение, health=свежесть, `last_heartbeat_at`; FK отложены — ADR-0013;
  партиал-индекс «≤1 живой инстанс/счёт», OPS3/MON2).

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

## Запуск (dev) / тесты
`docker compose -f infra/docker-compose.dev.yml up -d --wait` → в `core/`: `alembic upgrade head` ·
`uvicorn app.main:app` · `pytest` (нужен `DATABASE_URL`). CI: `.github/workflows/ci.yml`
(ruff+pytest на свежем Postgres — гейт §2).
⚠️ macOS: если `import psycopg`/`argon2` висит — `xattr -dr com.apple.quarantine .venv` (Gatekeeper).

## Ещё нет (следующие шаги)
outbox-алерты (доставка stale/dead Оператору); internal API jobs для оркестратора; остальной домен
clients/jobs/telemetry/billing (свои миграции); биржевые ключи (Ф2); биллинг HWM (Ф3).
