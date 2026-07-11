---
type: index
title: Каталог вики Цитадели
updated: 2026-07-10
---
# Индекс (одна строка на страницу)

- [roadmap](roadmap.md) — вехи Ф0→Ф5 со статусами фич + Icebox.

## concepts
- [vision](concepts/vision.md) — зачем существует Цитадель, модель managed, не-цели.
- [glossary](concepts/glossary.md) — язык проекта: движок/тип бота/профиль/паспорт/инстанс/ансамбль/HWM.
- [architecture](concepts/architecture.md) — 4 модуля вокруг ядра, потоки, трубы фундамента.
- [seams](concepts/seams.md) — каталог швов: 8 границ, контракты, отказы, заглушки (единый источник).
- [flows](concepts/flows.md) — трассировки деплоя и STOP_CLOSE по швам + машина состояний инстанса.
- [seams-review](concepts/seams-review.md) — триаж 68 адверсариальных находок MFC-000 (⛔ до кода).
- [core-api](concepts/core-api.md) — API ядра на MFC-001: ручки, auth, миграции, запуск.
- [domain-model](concepts/domain-model.md) — таблицы домена (единый источник; миграция 0001 отсюда).
- [bot-contract](concepts/bot-contract.md) — Контракт Бота v0: вход/телеметрия/команды/гарантии.
- [telemetry-schemas](concepts/telemetry-schemas.md) — заглушка: JSON-схемы появятся с paper-bot (schema-first).
- [threat-model](concepts/threat-model.md) — 9 угроз и ответы платформы.
- [keys-policy](concepts/keys-policy.md) — жизненный цикл ключей клиента.

## decisions (ADR)
- [0001](decisions/0001-platform-vs-engines.md) — платформа ≠ движки; Контракт Бота.
- [0002](decisions/0002-bot-contract.md) — три канала контракта; без входящих портов у ботов.
- [0003](decisions/0003-railway-first.md) — Railway v1 через InfraDriver; факты и цены; план Б VPS.
- [0004](decisions/0004-secrets-envelope.md) — конверт-шифрование ключей; master-key у оркестратора.
- [0005](decisions/0005-client-killswitch.md) — клиентский стоп двухступенчатый (Пауза / Стоп-и-закрыть).
- [0006](decisions/0006-ensembles-pipe.md) — труба под бота-дирижёра (ансамбли).
- [0007](decisions/0007-bot-db-schema-per-instance.md) — кластер ботов, схема-на-инстанс + изоляция роли (v2).
- [0008](decisions/0008-auth-model.md) — единый opaque-токен-механизм всем + TOTP Оператора (v2).
- [0009](decisions/0009-jobs-transport.md) — jobs через internal API (long-poll+lease+fencing) (v2).
- [0010](decisions/0010-key-intake-asymmetric.md) — асимметричный конверт + allowlist образа (v2, уточняет 0004).
- [0011](decisions/0011-billing-hwm-model.md) — модель HWM (cashflows, уровень счёта, сверка); формула — Ф3.
- [0012](decisions/0012-healthz-scheduler-deadman.md) — dead-man часового в /healthz (вариант A: показывать, не гейтить).
- [0013](decisions/0013-instances-deferred-fk.md) — отложенные FK у instances (материализуем без родителей, YAGNI).

## runbooks
- [onboarding-client](runbooks/onboarding-client.md) — путь клиента до go-live.
- [deploy-instance](runbooks/deploy-instance.md) — деплой/откат инстанса.
- [alerts](runbooks/alerts.md) — что будит Оператора в Telegram.
- [key-rotation](runbooks/key-rotation.md) — ротация/отзыв ключа биржи (каркас, Ф2).
- [railway-shakedown](runbooks/railway-shakedown.md) — обкатка Railway на живом paper-bot; ⛔ гейт токена Оператора.

## research
- [passport-spec](research/passport-spec.md) — паспорт профиля; OOS обязателен (закон Кузницы).

## legal
- [disclaimers-draft](legal/disclaimers-draft.md) — черновик оговорок; ⚠️ юрист до первого клиента.

## entities
- [pifagor-engine](entities/pifagor-engine.md) · [bybit](entities/bybit.md) · [okx](entities/okx.md)
  · [bitget](entities/bitget.md) · [railway](entities/railway.md)

## summaries
- [karpathy-llm-wiki](summaries/karpathy-llm-wiki.md) — принятый стандарт ведения БЗ.
- [gbrain](summaries/gbrain.md) — идеи на будущее для Исследований.

## handoffs
- [_TEMPLATE](handoffs/_TEMPLATE.md)
- [HANDOFF_2026-07-10_session_1](handoffs/HANDOFF_2026-07-10_session_1.md) — сессия-основание: концепция, 6 ADR, скелет, вики.
- [HANDOFF_2026-07-11_session_2](handoffs/HANDOFF_2026-07-11_session_2.md) — MFC-000 швы + ADR 0007–0011, GOV-1, MFC-001 core (merged).
- [HANDOFF_2026-07-11_session_3](handoffs/HANDOFF_2026-07-11_session_3.md) — MFC-002 часовой + MFC-003 instances/stale-скан (ADR 0012–0013, merged).
- [HANDOFF_2026-07-11_session_4](handoffs/HANDOFF_2026-07-11_session_4.md) — Ф1 закрыта (MFC-004/005/006 + Railway обкатка merged); Ф2 начата (снимок Пифагора b75bd17 вендорен).
