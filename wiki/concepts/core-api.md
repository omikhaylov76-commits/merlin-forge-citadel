---
type: concept
title: API ядра (core) — состояние MFC-001
tags: [core, api, auth]
updated: 2026-07-11
sources: [core/, decisions/0008, 0009, 0010]
---
# API ядра (core)

Реализовано в MFC-001 (скелет). FastAPI app-factory (`create_app`), структурный JSON-лог с request-id.
Это состояние на сегодня; полный домен и швы — [domain-model](domain-model.md) / [seams](seams.md).

## Ручки
- `GET /healthz` — liveness (без БД).
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
- 0001: `users` (role строка+CHECK), `api_tokens` (хэш SHA-256), `audit_log` (+триггер append-only).
- 0002: `users.email` (уникальный) — идентификатор логина.

## Наблюдаемость
request-id на каждый запрос (заголовок `X-Request-ID` + строки лога) для сшивки с audit_log.
Каждое действие оператора/клиента — строка `audit_log` (закон №4); секреты не логируются (закон №2).

## Запуск (dev) / тесты
`docker compose -f infra/docker-compose.dev.yml up -d --wait` → в `core/`: `alembic upgrade head` ·
`uvicorn app.main:app` · `pytest` (нужен `DATABASE_URL`). CI: `.github/workflows/ci.yml`
(ruff+pytest на свежем Postgres — гейт §2).
⚠️ macOS: если `import psycopg`/`argon2` висит — `xattr -dr com.apple.quarantine .venv` (Gatekeeper).

## Ещё нет (следующие шаги)
core-scheduler «часовой» (MFC-002); internal API jobs для оркестратора; домен
instances/jobs/telemetry/billing (свои миграции); биржевые ключи (Ф2); биллинг HWM (Ф3).
