# core — ядро платформы
Единственный владелец Postgres. FastAPI (app-factory). Внутри: домен (wiki/concepts/domain-model.md),
REST API (консоль/портал/боты) + internal API оркестратору (аренда jobs, ADR-0009), auth
(единый opaque-токен ADR-0008v2 + TOTP-заготовка), audit_log (append-only, закон №4),
структурный лог с request-id. Позже: биллинг HWM, outbox-алерты, core-scheduler (MFC-002).
Не знает: как устроены движки, как деплоятся контейнеры (это оркестратор через jobs).

Запуск (dev): `docker compose -f infra/docker-compose.dev.yml up -d --wait`, затем в `core/`:
`alembic upgrade head` → `uvicorn app.main:app`. Тесты: `pytest` (нужен `DATABASE_URL`).
Проверки: `/healthz` (liveness), `/readyz` (БД+миграции). Полная карточка API — wiki/concepts/core-api.md.
