---
type: log
title: Журнал операций вики (append-only)
---
# Журнал (новые записи СНИЗУ, ничего не удалять)

- 2026-07-09 · Куратор · Сессия-основание: разведка pifagor-v81 (ядро прочитано), развилки
  Оператора решены (Bybit-first, HWM %, портал read-only), пивот на платформу с нуля.
- 2026-07-10 · Куратор · Имя: Merlin Forge Citadel. Заложены ADR 0001–0006, Контракт Бота v0,
  модель угроз, скелет монорепо (32 файла). Проверен Railway (API/цены/static IP — см. entities/railway).
- 2026-07-10 · Куратор · База знаний переведена на паттерн Karpathy-вики (index/log/concepts/
  entities/summaries + правила в CLAUDE.md). Введены entities бирж и summaries источников.
- 2026-07-10 · Куратор · Session 1 закрыта: handoff в wiki/handoffs/, скелет разложен в папку Оператора, CLOSURE-1 (git+GitHub) передан Инженеру.
- 2026-07-10 · Куратор · Maestro Kit 1.0.0 опубликован (github.com/omikhaylov76-commits/maestro-kit, public, MIT). Цитадель дальше ведётся под его /build; её wiki уже в формате Маэстро.
- 2026-07-10 · Куратор · Maestro Kit .claude установлен в Цитадель (build/status/wiki/handoff + code-reviewer). Проект готов вестись под /build.
- 2026-07-10 · Инженер · Roadmap Ф0→Ф5 материализован в wiki/roadmap.md (из handoff S1), полка progress/ развёрнута.
- 2026-07-10 · Инженер · CLOSURE-1 закрыт: git init, коммиты foundation v0.1 + roadmap, приватный GitHub omikhaylov76-commits/merlin-forge-citadel, push в main.
- 2026-07-10 · Инженер · MFC-000 стартовал: глубокая проработка швов и контрактов до кода (задача Куратора).
- 2026-07-10 · Куратор · Maestro Kit 1.1.0: ШАГ 3.7 «Глубокая проработка швов» зашит в набор (обобщён из MFC-000). Копия в Цитадели обновлена.
- 2026-07-10 · Инженер · MFC-000 синтез: seams.md (8 швов) + flows.md (2 трассировки, машина состояний) + ADR 0007–0010 (proposed) + угроза №8; развилки вынесены на ⛔ Куратору.
- 2026-07-10 · Инженер · MFC-000 адверсариальный прогон: 5 скептиков, 68 находок (seams-review.md); domain-model приведён к дизайну, ADR 0007–0010 получили v2, добавлен 0011 (биллинг HWM), ~15 правок связности. Ждёт вердикт Куратора.
- 2026-07-10 · Куратор+Инженер · ADR 0007–0011 приняты (accepted), включая разворот 0008 (единый opaque-токен-механизм вместо JWT). MFC-000 закрыт: швы проработаны и закалены адверсариально до первой строки кода.
- 2026-07-11 · Инженер · MFC-001 core-скелет готов: FastAPI + Alembic (миграции 0001/0002) + /healthz+/readyz + auth (opaque-токены/RBAC/владение/аудит, ADR-0008v2) + CI (гейт §2). Все шаги зелёные локально и в GitHub Actions.
- 2026-07-11 · Инженер · MFC-001 слит в main (e3b13a2, --no-ff): core-скелет FastAPI+Alembic+auth+CI, code-review ×2, 14 тестов зелёные. Первая боевая фича платформы закрыта.
- 2026-07-11 · Инженер · Handoff session 2 → 3 (wiki/handoffs/HANDOFF_2026-07-11_session_2.md): MFC-000/GOV-1/MFC-001 закрыты, следующее — MFC-002 (core-scheduler).
- 2026-07-11 · Инженер · MFC-002 core-scheduler «часовой»: asyncio-цикл + реестр свёрток + dead-man тик в /healthz (вариант A, ADR-0012). pytest 19 зелёных, ruff clean; живой uvicorn показал running + сброс tick_age. Ветка task/mfc-002.
- 2026-07-11 · Инженер · MFC-002 слит в main (2b2c01a, --no-ff): часовой закрыт. Независимое адверсариальное ревью — блокер Event-между-loop закрыт + 3 ловушки; регресс-тест; pytest 20 зелёных. Ветка task/mfc-002 удалена.
- 2026-07-11 · Инженер · MFC-003: instances (миграция 0002) + первая боевая свёртка часового — stale-скан heartbeat (health ok/stale/dead + audit, ADR-0013 отложенные FK; партиал-индекс ≤1 живой/счёт). Живой uvicorn флипнул health сам; pytest 24 зелёных. Попутно: doc «0002:email» устарел (email в 0001) — починен в core-api. Ветка task/mfc-003.
- 2026-07-11 · Инженер · MFC-003 слит в main (b963b55, --no-ff): instances + stale-скан закрыты. Независимое адверсариальное ревью — advisory-lock single-writer (защита append-only audit, закон №4), валидатор порогов, +4 теста; pytest 28 зелёных. Ветка task/mfc-003 удалена. В Icebox Куратору: дефолт health='ok' для never-reported + глобальный sessionmaker.
- 2026-07-11 · Инженер · Handoff session 3 → 4 (wiki/handoffs/HANDOFF_2026-07-11_session_3.md): MFC-002 «часовой» + MFC-003 instances/stale-скан закрыты и слиты; следующее — оркестратор + InfraDriver.
