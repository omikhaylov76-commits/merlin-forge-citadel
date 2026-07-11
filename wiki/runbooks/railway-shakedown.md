---
type: runbook
title: Обкатка Railway на живом paper-bot (проверка допущения №3)
tags: [runbook, railway, orchestrator, shakedown, gate]
updated: 2026-07-11
sources: [decisions/0003-railway-first.md, entities/railway.md, orchestrator/app/infra/railway.py]
---
# Обкатка Railway на живом paper-bot

**Зачем.** RailwayDriver (MFC-004) структурно готов, но точная схема Railway GraphQL v2
(serviceCreate/serviceDelete/поиск сервисов, environmentId, variableCollectionUpsert, redeploy)
проверялась только через MockTransport. Эта обкатка сверяет её с ЖИВЫМ Railway на одном paper-bot
и чинит расхождения в `orchestrator/app/infra/railway.py`. Это проверка допущения №3 handoff'а.

## ⛔ ГЕЙТ ОПЕРАТОРА (ключи/деньги/внешнее)
Живой прогон требует того, что Инженер автономно не делает:
1. **RAILWAY_API_TOKEN** — реальный ключ (Оператор кладёт в env, Инженеру его не видеть/не вводить).
2. **RAILWAY_PROJECT_ID** — проект Railway (создать в формате мульти-проект СРАЗУ, SCL8).
3. **Согласие на внешний деплой** — реальная инфраструктура + микро-стоимость compute (D2: Railway Pro
   НЕ включать; static IP не нужен для paper). Мейннет/ключи бирж — НЕ здесь (paper-only).

## Готово автономно (до гейта)
- Образ картриджа: `bots/paper-bot/Dockerfile` (собирается: `docker build -t mfc-paper-bot:v0 bots/paper-bot`,
  проверено). Railway может собрать из Dockerfile репо или тянуть образ из реестра.
- RailwayDriver: `deploy`(усынови-или-создай по имени mfc-inst-{id}) · `destroy`(идемпотентно) · `status`.
- Оркестратор: `DRIVER=railway` + `RAILWAY_API_TOKEN`/`RAILWAY_PROJECT_ID` в конфиге.

## Шаги (когда токен есть)
1. Поднять оркестратор с `DRIVER=railway`, живым токеном и project_id.
2. Через ядро: `POST /v1/instances` (образ = paper-bot) → deploy-job; оркестратор арендует и зовёт
   RailwayDriver.deploy на ЖИВОЙ Railway.
3. **Сверить GraphQL точечно** (главная цель): пройти реальные ответы Railway на findService/serviceCreate/
   serviceDelete; где схема разошлась с `railway.py` (имена полей, environmentId, форма serviceCreate,
   redeploy+variableCollectionUpsert) — починить драйвер и обновить `entities/railway.md`.
4. Проверить сквозняк: сервис `mfc-inst-{id}` поднялся → paper-bot шлёт heartbeat/телеметрию в ядро →
   инстанс running/health ok → команда pause/stop_close честно отработала (как в сквозняке MFC-006).
5. `destroy`: снести сервис, подтвердить идемпотентность (404 = успех, OPS5). Убедиться, что счёт освобождён.
6. Измерить квоты Railway (сервисов/проект, rate-limit GraphQL) → занести в `entities/railway.md` (ADR-0003).

## Отказы / откат
Дубль сервиса после create (create не атомарен с поиском, OPS2) — усыновить по имени, лишний снести.
Любой живой сервис после обкатки — снести (`destroy`), чтобы не капал compute. OPS13-reconcile сирот
(reconcile instances↔`mfc-inst-*`) — ОТДЕЛЬНАЯ MFC, гейт до Ф2 (разбор Куратора #2).

## Результат обкатки 2026-07-11 (deployability ✅ через CLI)
Через Railway CLI (авторизован Оператором) в изолированном проекте `mfc-paper-shakedown`:
- **Railway СОБРАЛ наш Dockerfile** (build-логи: python:3.12-slim → COPY app → pip install → образ, push).
- **Railway ЗАПУСТИЛ наш процесс**: рантайм-логи показали наш код (`bot.py tick_once → client heartbeat →
  httpx.post`) с `ConnectError: Connection refused` к локальному `MF_CORE_URL` — ожидаемо (ядро локальное,
  из контейнера недостижимо); best-effort ловит и продолжает. Картридж живёт на Railway.
- Прибрано: `railway down` + удаление проекта (`Project is deleted`) — compute не капает.

**Допущение №3 на уровне деплоя подтверждено: Railway собирает и гоняет наш картридж.**

## Осталось (полная сверка драйвера — меньший, гейтованный шаг)
CLI-деплой обошёл сам `RailwayDriver` (использовал `railway up`, не orchestrator→GraphQL). Чтобы закрыть
сверку GraphQL-схемы драйвера (главная цель), нужно: (1) образ paper-bot в реестре (GHCR/Docker Hub —
serviceCreate драйвера принимает image, не сборку-из-исходников); (2) **RAILWAY_API_TOKEN** в env
оркестратора (Оператор заводит в дашборде, кладёт сам); (3) прогон orchestrator `DRIVER=railway` →
реальные ответы Railway на find/create/delete → починить `railway.py` где схема разошлась. Отдельный заход.

## После полной сверки
Схема GraphQL подтверждена/починена → Ф1 закрыта. Дальше — **гейт Ф2**: снимок Пифагора (Оператор
подтверждает коммит).
