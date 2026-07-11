# HANDOFF: Session 2 → Session 3

**From:** Session 2 (Инженер, Claude Code) · **Date:** 2026-07-11
**Веха:** Ф1 «Forge на paper-bot» · **Фича:** MFC-001 ✅ merged · **Следующее:** MFC-002

---

## 1. Состояние
Первая боевая фича на `main`. Ядро (core) поднимается, все проверки зелёные локально и в CI (Linux).
- Работает: FastAPI app-factory · `/healthz` (liveness) · `/readyz` (БД+миграции) · Alembic
  миграция 0001 (`users`/`api_tokens`/`audit_log`, audit **append-only на уровне БД**) ·
  auth ADR-0008v2 (opaque-токены SHA-256, argon2-пароль, RBAC, владение на всех ручках, аудит
  + `login_failed`, TOTP-заготовка) · CI-гейт §2 (GitHub Actions + Postgres).
- **Тесты:** 14 passed (pytest в `core/`, нужен `DATABASE_URL`). **CI:** зелёный на main.

## 2. Сделано в сессии
- **MFC-000** — глубокая проработка швов до кода: `seams.md`, `flows.md`, `domain-model` приведён
  к дизайну; **адверсариальный прогон 5 скептиков (68 находок)** → `seams-review.md`; ADR **0007–0011**.
- **GOV-1** — реконсиляция конституции: README закон №2, WORKING_AGREEMENTS §2 (веточная политика),
  CLAUDE.md (перечень вики), модульные README ↔ ADR-0009; Maestro Kit 1.2.0.
- **MFC-001** — core-скелет по 5 шагам с доказательством на каждом + фиксы двух кругов code-review;
  слит в main (`e3b13a2`, --no-ff).

## 3. Решения сессии (оформлены в ADR/вики)
- **ADR 0007–0011 accepted:** БД-ботов схема-на-инстанс · auth = единый opaque-токен (разворот 0008,
  без JWT) · jobs через internal API+lease · асимметричный конверт ключей (уточняет 0004) ·
  модель HWM (направление; формула — Ф3).
- **MFC-001:** роль = STRING+CHECK (не ENUM) · argon2 только пароль, SHA-256 токены · «часовой»
  отложен в MFC-002 · **CI — источник правды** (локальный Docker на macOS ненадёжен) · email в
  миграции 0001 · логин константного времени + аудит `login_failed`.

## 4. Код
- **Ветка:** `main` (HEAD `0065ba1`). Фича-ветка `task/mfc-001` слита — **подлежит удалению** (см. §7).
- **Незакоммиченного нет**, дерево чистое.
- **CI:** `.github/workflows/ci.yml` — ruff+pytest на Postgres. Гейт §2.

## 5. Открытые вопросы
**Оператору (async, из Ф0):** мокап консоли (блокер — дизайн-папка в iCloud не скачана) · юрист/договор до первого клиента.
**До go-live (roadmap-гвозди):** включить TOTP Оператора · rate-limit логина.
**Icebox (хвосты code-review):** request-id генерировать серверно/валидировать · троттлить запись
скользящего TTL · `users.is_active` · функциональный уникальный индекс `lower(email)` (когда появится ручка создания юзера).

## 6. Следующий шаг (конкретно)
**MFC-002 — core-scheduler «часовой»:** один asyncio-цикл + реестр свёрток; первая реальная свёртка —
dead-man тик диспетчера в `/healthz` (SCL3), затем stale-скан heartbeat. Ветка `task/mfc-002`, цикл /build.
(Альтернатива по roadmap: сразу оркестратор + InfraDriver + paper-bot — если Куратор решит иначе.)

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -3` показывает merge `e3b13a2` (MFC-001) на main.
- [ ] CI на main зелёный (GitHub Actions).
- [ ] Локально перед прогоном БД: `open -a Docker`; `docker compose -f infra/docker-compose.dev.yml up -d --wait`.
- [ ] ⚠️ macOS: если `import psycopg`/`argon2` висит → `xattr -dr com.apple.quarantine core/.venv` (Gatekeeper).
- [ ] `cd core && DATABASE_URL=postgresql+psycopg://mfc:mfc@127.0.0.1:5432/mfc_core .venv/bin/pytest -q` → 14 passed.
- [ ] `wiki/roadmap.md`: MFC-001 `merged: yes`, MFC-002 `todo`, Ф0 `closed`.
- [ ] ADR 0007–0011 = accepted; `seams`/`flows`/`core-api` актуальны (index.md — каталог).
- [ ] Ветка `task/mfc-001` удалена (local + origin) — если нет, удалить.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 2 → Session 3.
