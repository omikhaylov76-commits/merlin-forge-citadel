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
- [telemetry-schemas](concepts/telemetry-schemas.md) — JSON-схемы Контракта (v1): 5 каналов телеметрии (+scout) + команды; schema-first, sync-гвозди.
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
- [0014](decisions/0014-malysh-merlin-reference.md) — «Малыш Мерлин»: архив @b75bd17 + тег + залоченный профиль-эталон + инвариант «клонируй-не-редактируй».
- [0015](decisions/0015-cartridge-deploy-registry-model.md) — модель деплоя картриджей: публичный образ на демо (hobby) → приватный+registry-cred на go-live (Pro/Docker); C отклонён.
- [0016](decisions/0016-scout-channel-onboard-scout.md) — scout-канал Контракта v1 (5-й, replace-снимок сетапов) + онбординг штатного скаута из обёртки; закон №6 уточнён; 6 условий включения (fail-closed); go-live гейт.

## reference
- [reference/README](../reference/README.md) — «Малыш Мерлин»: профиль-эталон v8.3 (в дереве) + архив @b75bd17 (release-ассет, SHA256) + инвариант.
- [reference/fleet-live-config](../reference/fleet-live-config.json) — база флота ×5 «Живой V3 (demo)» (23 крутилки, KILLSWITCH_DD=0.70; НЕ эталон, #47).
- [reference/fleet-v3-configdiff](../reference/fleet-v3-configdiff.json) — #47: дамп 23 крутилок воркера флота == fleet-live-config (V3), drift=[] (live: knobs(eff) risk 2.5/cap 16).
- [reference/perceval-configdiff-b75bd17](../reference/perceval-configdiff-b75bd17.json) — #43 Шаг A: конфиг-diff Персиваля vs эталон @b75bd17, drift=[] (аудируемый артефакт, #44).

## runbooks
- [onboarding-client](runbooks/onboarding-client.md) — путь клиента до go-live.
- [deploy-instance](runbooks/deploy-instance.md) — деплой/откат инстанса.
- [alerts](runbooks/alerts.md) — что будит Оператора в Telegram.
- [key-rotation](runbooks/key-rotation.md) — ротация/отзыв ключа биржи (каркас, Ф2).
- [railway-shakedown](runbooks/railway-shakedown.md) — обкатка Railway на живом paper-bot; ⛔ гейт токена Оператора.
- [pifagor-cartridge-deploy](runbooks/pifagor-cartridge-deploy.md) — деплой картриджа Пифагора (ghcr→Railway, безопасный режим); ⛔ гейт Оператора (ghcr-доступ + demo-ключи).

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
- [HANDOFF_2026-07-12_session_5](handoffs/HANDOFF_2026-07-12_session_5.md) — **Ф2 ЗАКРЫТА**: адаптер картриджа + облачная сборка + ядро/Postgres/картридж в облаке, сквозняк облако-в-облако. Дальше — Малыш Мерлин (#11).
- [HANDOFF_2026-07-15_session_6](handoffs/HANDOFF_2026-07-15_session_6.md) — **Ф3 денежный блок построен+отревьюен**: #20, Малыш Мерлин (ADR-0014), CRM-схема, движок HWM (ADR-0011), CRM-API, генератор периодов. Осталось Telegram (отложено). main @ 15abecb.
- [HANDOFF_2026-07-16_session_8](handoffs/HANDOFF_2026-07-16_session_8.md) — **#47 демо-флот 5× «Живой V3» в облаке**: Персиваль в demo-LIVE (FC1 $20K, kill −70%, 0 ордеров — ждёт сетап), 4 припаркованы dry-run. ADR-0015, драйвер+bootstrap+вливка ключей, консоль на живьё. main @ 0bc8d10.
- [HANDOFF_2026-07-15_session_7](handoffs/HANDOFF_2026-07-15_session_7.md) — **Ф4 консоль построена+доведена** (#36–#42: fleet-эндпоинт, логин, адаптив 1880, живой Обзор, floor 900px) + **#43 Шаг A «Персиваль»** локальный сквозняк доказан (конфиг-diff 23 крутилки == эталон без дрейфа). main @ bd3e761. Дальше — Шаг B/передеплой облака по гейту.
- [HANDOFF_2026-07-16_session_9](handoffs/HANDOFF_2026-07-16_session_9.md) — **#54 скаут ВЖИВУЮ на Галахаде** (труба на реальном рынке, 2 бага чинены) + **облачная консоль #53+#56** + **Персиваль kill-switch** разблокирован (находка: эфемерная БД) + **пакет S6 закрыт**: П1 #57 persistent volume Персивалю, П2 сторож в геном+курсор, П3 #56 график. main @ b364779. Дальше — ждём Куратора (П4/хранитель/REBASELINE_RISK) + Оператора (#56).
- [HANDOFF_2026-07-17_session_10](handoffs/HANDOFF_2026-07-17_session_10.md) — **S7 «Разведка-стол» закрыт end-to-end**: настройки дозора ядро(0013/ADR-0018)→картридж(boot-fetch+3 стража)→консоль(плашка+рояль по макетам); 2 живых бага починены (scan_now: mark→request_scan; «Применить» → force_recalibrate, иначе список не пересобирался); сквозная сверка с эталонным движком 23/25. Дизайн принят Оператором. main @ 944bebd. Открыто: 2 гапа Куратору (primary_tf-редактор, превью «N пройдёт»).
- [HANDOFF_2026-07-18_session_11](handoffs/HANDOFF_2026-07-18_session_11.md) — **S8 «Динамо-близнец» Веха 1: Слои 1–2 (разъём генома + провайдер) в main, CI зелёный.** Путь Б: разъём COINS_CONFIG_PATH в vendor/strategy.py (ADR-0019 — амендмент Закона 6/ADR-0016 «0 vendor» + страж-дрейфа CI) + провайдер dynamic_universe (стек/пол-на-пустоту/гистерезис/анти-thrash) + супервизор движка + engine_state.stack. Дормантно (DYNAMIC_ENABLED off) — флот/Персиваль байт-в-байт. main @ f7dc001. Дальше: Слой 3 (консоль раздел 5 + ADR-0020 канал критериев) + Слой 4 (деплой Борса).
- [ADR-0017 — Набор Оператора (НАБОР-1): витрина+хранение отмеченных сетапов](decisions/0017-basket-nabor-1.md)
- [progress/nabor-1 — корзина сетапов: ядро+консоль, ничего не торгует](progress/nabor-1.md)
