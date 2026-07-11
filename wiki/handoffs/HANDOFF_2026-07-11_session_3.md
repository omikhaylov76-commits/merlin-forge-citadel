# HANDOFF: Session 3 → Session 4

**From:** Session 3 (Инженер, Claude Code) · **Date:** 2026-07-11
**Веха:** Ф1 «Forge на paper-bot» · **Закрыто:** MFC-002 + MFC-003 (обе merged) · **Следующее:** оркестратор

---

## 1. Состояние
Ядро выросло на две фичи; всё зелёное локально и в CI. HEAD main — `b8a37d6`.
- Работает: FastAPI app-factory · `/healthz` (liveness + блок `scheduler` dead-man) · `/readyz` ·
  Alembic (0001 users/api_tokens/audit_log; **0002 instances**) · auth (opaque-токены/RBAC/владение/
  аудит, ADR-0008v2) · **core-scheduler «часовой»** (asyncio-цикл + реестр свёрток + dead-man тик,
  ADR-0012) · **первая боевая свёртка — stale-скан** (health ok→stale→dead по свежести heartbeat,
  audit, advisory-lock single-writer) · CI-гейт §2.
- **Тесты:** 28 passed (pytest в `core/`, нужен `DATABASE_URL`). **CI:** зелёный на main.

## 2. Сделано в сессии
- Прошёл §7 хэндоффа S2 (все проверки: 14 тестов, CI, ветка mfc-001 удалена).
- **MFC-002 «часовой»:** один asyncio-цикл + реестр свёрток + dead-man тик в `/healthz`. Независимое
  адверсариальное ревью нашло блокер (Event создавался в `__init__` → падал при переиспользовании
  между event-loop) — закрыт. Merged `2b2c01a`.
- **MFC-003 instances + stale-скан:** таблица `instances` (миграция 0002) + первая боевая свёртка
  часового. Ревью: 4 🟡 закрыты (advisory-lock, валидатор порогов, +4 теста). Merged `b963b55`.
- Lint: починен устаревший doc «0002: users.email» (email — в миграции 0001).

## 3. Решения сессии (оформлены в ADR/вики)
- **ADR-0012 accepted:** dead-man часового в `/healthz` — **вариант A** (показывать `scheduler.state`
  в теле, верхний `status` не гейтит; авто-рестарт по dead — не сейчас).
- **ADR-0013 accepted:** FK у `instances` **отложены** (колонки-ссылки NOT NULL без FK-constraint;
  родители появятся со своими фичами Ф2/Ф3/Ф5). Осознанный YAGNI, не полудорога.
- Свёртки часового = sync-функции через `asyncio.to_thread` (БД-сессия не блокирует цикл, SCL1);
  реестр — плагин-точка. Свёртка single-writer через `pg_try_advisory_xact_lock` (защита audit).

## 4. Код
- **Ветка:** `main` (HEAD `b8a37d6`). Фича-ветки `task/mfc-002` и `task/mfc-003` слиты и **удалены**.
- **Незакоммиченного кода нет**, дерево чистое. (Этот handoff + строки log/index — не закоммичены, см. §7.)
- **CI:** зелёный на main. Аннотация: Node 20 deprecation у actions/checkout@v4, setup-python@v5 (chore).

## 5. Открытые вопросы
**Куратору (Icebox из ревью MFC-003):** дефолт `health='ok'` для ни-разу-не-рапортовавшего инстанса —
ложно-зелёный; ввести `unknown`/`pending` или дефолт `stale` (вместе с deploy-watch Ф2). Свёртка/ядро
берут глобальный `get_sessionmaker` (пред-существующее). **Куратору (из прошлого):** мокап консоли
(iCloud), юрист/договор. **До go-live:** TOTP Оператора, rate-limit логина.

## 6. Следующий шаг (конкретно)
**Оркестратор + InfraDriver:** internal API jobs (аренда long-poll + lease + fencing, ADR-0009) +
драйвер Railway (GraphQL, интерфейс абстрагирован; план Б — DockerDriver). Recon: ADR-0009, швы
S3/S5 в `seams.md`. Таблица `jobs` создаётся в этой фиче (со своим потребителем). Ветка `task/mfc-004`,
цикл /build. (Альтернатива: paper-bot — но деплой всё равно через оркестратор.)

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -3` показывает merge `b963b55` (MFC-003) + `b8a37d6`.
- [ ] CI на main зелёный (GitHub Actions).
- [ ] Docker + dev DB: `open -a Docker`; `docker compose -f infra/docker-compose.dev.yml up -d --wait`.
- [ ] ⚠️ macOS: если `import psycopg`/`argon2` висит → `xattr -dr com.apple.quarantine core/.venv`.
- [ ] `cd core && DATABASE_URL=postgresql+psycopg://mfc:mfc@127.0.0.1:5432/mfc_core .venv/bin/pytest -q` → 28 passed.
- [ ] `wiki/roadmap.md`: MFC-002 и MFC-003 `merged: yes`; Ф1 in-progress; следующее — оркестратор.
- [ ] ADR 0012, 0013 = accepted; `core-api`/`domain-model`/`seams` актуальны (0002 instances, свёртка).
- [ ] Ветки: только `main` (task/mfc-002, task/mfc-003 удалены); **закоммитить этот handoff + log/index**.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 3 → Session 4.
