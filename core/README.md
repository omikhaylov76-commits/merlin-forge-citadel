# core — ядро платформы
Единственный владелец Postgres. FastAPI (app-factory). Внутри: домен (wiki/concepts/domain-model.md),
REST API (консоль/портал/боты) + internal API оркестратору (аренда jobs, ADR-0009), auth
(единый opaque-токен ADR-0008v2 + TOTP-заготовка), audit_log (append-only, закон №4),
структурный лог с request-id, core-scheduler «часовой» (dead-man в /healthz, MFC-002, ADR-0012).
Позже: биллинг HWM, outbox-алерты, stale-скан heartbeat. Не знает: как устроены движки, как
деплоятся контейнеры (это оркестратор через jobs).

Запуск (dev): `docker compose -f infra/docker-compose.dev.yml up -d --wait`, затем в `core/`:
`alembic upgrade head` → `uvicorn app.main:app`. Тесты: `pytest` (нужен `DATABASE_URL`).
Проверки: `/healthz` (liveness + блок scheduler), `/readyz` (БД+миграции). Полная карточка API — wiki/concepts/core-api.md.
