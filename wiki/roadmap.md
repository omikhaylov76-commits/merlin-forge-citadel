---
type: roadmap
title: Дорожная карта Merlin Forge Citadel
tags: [roadmap, phases]
updated: 2026-07-10
sources: [handoffs/HANDOFF_2026-07-10_session_1.md]
---
# Roadmap: вехи → фичи

Оценка всего пути (Ф0→Ф5): 22–35 сессий. Статусы: todo / in-progress / done.

## Ф0 — Подготовка (closed 2026-07-10)
Цель: конституция, решения, скелет, база знаний — фундамент до первой строчки кода.
- [x] Концепция + 6 ADR (0001–0006) — done
- [x] Вики по паттерну Карпати (index/log/concepts/entities/…) — done
- [x] Скелет монорепо (модули + README-манифесты границ) — done
- [x] Перевод проекта под Maestro Kit (/build, набор 1.2.0) — done
- [x] CLOSURE-1: git init + приватный GitHub + push — done · merged: yes (main, 2026-07-10)
- [x] MFC-000 швы + ADR 0007–0011 + GOV-1 реконсиляция — done (05c89bd)
- [→] Мокап консоли — перенесён в Ф1 (блокер: iCloud-папка не скачана), не гейт Ф0
- [→] Юрисдикция/договор — standing async за Оператором (до первого внешнего клиента)

## Ф1 — Forge: флот на paper-bot (in-progress)
Цель: конвейер платформы целиком, без денег — на бумажном боте.
- [x] MFC-000 проработка швов (pre-code): seams/flows/domain + ADR 0007–0011 (accepted 2026-07-10)
      + адверсариальный прогон (68 находок, seams-review.md) — done 2026-07-10
- [x] MFC-001 core-скелет: FastAPI + Alembic (0001) + /healthz+/readyz + auth (opaque-токены/
      RBAC/владение/аудит, ADR-0008v2) + CI (гейт §2) — done 2026-07-11 · merged: yes (main e3b13a2).
      «Часовой» вынесен в MFC-002.
- [ ] MFC-001-доп из разбора: long-poll без БД-коннекта (нагруз-тест); индекс+ретеншн телеметрии —
      todo (инвариант ≤1 инстанс/счёт и last_heartbeat_at уже закрыты в MFC-003).
- [x] MFC-002 core-scheduler «часовой»: asyncio-цикл + реестр свёрток + dead-man тик в /healthz
      (вариант A, ADR-0012) — done 2026-07-11 · merged: yes (main 2b2c01a). Stale-скан heartbeat —
      следующая свёртка (ждёт схему инстансов).
- [x] MFC-003 instances + stale-скан: таблица инстансов (миграция 0002, FK отложены ADR-0013,
      ≤1 живой/счёт) + первая боевая свёртка часового (health ok→stale→dead по heartbeat, audit,
      advisory-lock single-writer) — done 2026-07-11 · merged: yes (main b963b55).
- [x] MFC-004 Оркестратор + InfraDriver: миграция 0003 jobs + internal API аренды/ack (шов S3, ADR-0009)
      + продюсеры instances/teardown; модуль orchestrator/ (InfraDriver ABC + Fake/Docker/Railway + worker)
      — done 2026-07-11 · merged: yes (main ed18bb9). Боевая обкатка Railway — ниже (⚠️ схема GraphQL).
- [x] MFC-005 core-сторона Контракта Бота (шов S4): schema-first схемы v0 (contracts/) + миграция 0004
      (equity/trades/events/commands) + instance-token auth + приём телеметрии (dedup/ts-skew) + команды
      (long-poll липкий stop_close + ack, ADR-0005) — done 2026-07-11 · merged: yes (main 99942f8).
- [x] MFC-006 paper-bot: эталонный картридж (bots/paper-bot) по Контракту v0 — детерминированный движок
      (синус+seeded), честные семантики ADR-0005 (pause держит позиции, stop_close закрыть+встать),
      клиент API S4 + цикл. Сквозняк вживую доказал pause/stop_close — done 2026-07-11 · merged: yes (main 0baacb9).
- [x] Обкатка Railway на живом paper-bot (допущение №3) — **done 2026-07-11**: (1) CLI собрал Dockerfile
      картриджа и запустил процесс (deployability); (2) `RailwayDriver` подтверждён на живом GraphQL API —
      полный цикл FindService→serviceCreate→status→serviceDelete ОК, формат infra_ref ок; найден+починен
      фикс `trust_env=False` (httpx висел). Оба тестовых проекта удалены. Ф1 технически закрыта → гейт Ф2.
- [ ] 🚧 MFC OPS13 reconcile сирот: свёртка часового сверяет instances↔сервисы `mfc-inst-*`, гасит
      сирот (разбор Куратора #2, вариант A). **Гейт: ДО Ф2** (до первого реального деплоя) — todo
- [ ] Консоль Оператора: минимальный флот-дашборд (после мокапа) — todo

## Ф2 — Пифагор-картридж (ЗАКРЫТА 2026-07-12) — план: progress/f2-pifagor-cartridge.md
Цель ДОСТИГНУТА: первый боевой движок за Контрактом, без правок pifagor-v81, живёт в облаке (Railway).
Снимок: main @ **b75bd17**. Осталось из веха как хвосты go-live: конверт-ключей + reference-hardening (ниже/Icebox).
- [x] Recon: dashboard/viewmodel.py (build_monitor отдаёт equity/curve/working/cushion/kill-switch/сделки) —
      допущение «обёртка без правок репо» **ПОДТВЕРЖДЕНО** 2026-07-11. Recon-2 (контролы pause/kill) — след.
- [x] Обёртка-адаптер: `bots/pifagor-cartridge` — read-only по Контракту (viewmodel→heartbeat/equity/trades/
      events + команды→PAUSE_ENABLED/killswitch, 4xx-классификация #6/#7) — done 2026-07-12 · 70 тестов +
      parity(реальный build_monitor) + schema-conformance; ЖИВОЙ сквозняк против ядра ✅; независимое ревью
      (фиксы #1–#5). Образ: облачная сборка CI→ghcr (#12), локальный Docker убран.
- [x] **Ф2 ЗАКРЫТА (2026-07-12): картридж Пифагора живой в облаке, сквозняк ОБЛАКО-В-ОБЛАКО (#15).**
      Railway-проект `merlin-forge-citadel`: Postgres + ядро (публичный `core-production-429b.up.railway.app`,
      healthz/readyz 200) + картридж (worker DEMO api-demo.bybit.com, safe LIVE_TRADING_ENABLED=0). Телеметрия
      картридж→облачное ядро (heartbeat 204/equity 202/events 202, приватная сеть) + pause сквозь ядро
      (enqueue→command_delivered→command_ack). Bootstrap ядра (оператор+instance-токен из env). Образы CI→ghcr.
- [x] Хардненинг #20 (2026-07-12, main cde329f): дыра-гигиена на ПУБЛИЧНОМ ядре закрыта — `create_app`
      по умолчанию отключает /docs·/redoc·/openapi.json (ENABLE_DOCS=1 для локали), +2 теста. Передеплой +
      сырой curl-простук без токена: доки 404, /v1/* и internal/telemetry без токена 401, healthz/readyz 200;
      Postgres не публичен; BOOTSTRAP_* сильные. **Ф2 БЕЗОПАСНО закрыта.**
- [x] «Малыш Мерлин» (#11) — **done 2026-07-12** (ADR-0014): полный архив @b75bd17 в 3 местах (annotated-тег
      `malysh-merlin/v8.3-b75bd17` + release на репо Пифагора; tar.gz-ассет release Цитадели, SHA256
      `04f81c61…` сверен; локальный клон Оператора) + залоченный профиль-эталон
      `reference/malysh-merlin-profile-v8.3.json` (23 крутилки, захват дефолтов из config.knobs @b75bd17) +
      инвариант «клонируй-не-редактируй». Полный залок в UI — Ф5. pifagor-v81 не тронут (только тег-указатель).
- [ ] Конверт-шифрование ключей биржи end-to-end (ADR-0004/0010) + тесты — todo (реальные ключи — только «go»)

## Ф3 — CRM + биллинг HWM (in-progress)
Цель: клиенты, договорные параметры, комиссия % от прибыли по high-water mark.
- [x] MFC-F3-1 CRM-схема (2026-07-14, main 532399c): таблицы clients + exchange_accounts (миграция 0005,
      CHECK fee/enum) + активация отложенных FK instances.client_id/account_id (ADR-0013 триггер) + бэкофилл
      сирот + bootstrap-родители + create_instance 404/400. CI зелёный. bot_type/profile FK — Ф5.
- [x] Финализировать ADR-0011 (модель HWM: месяц, cashflows, уровень счёта, сверка) — done (#27, accepted 2026-07-14)
- [x] Биллинг HWM + эталонные тесты (закон 8) — **done 2026-07-14 (main fb9983f)**: миграция 0006
      (contracts/billing_periods/cashflows + immutable-триггер + EXCLUDE overlap) + движок billing.py
      (compute_period + close_period, снапшот fee_pct, аудит commission_calculated). Адверс-ревью ×2
      (поймало critical money-баг порядка закрытия → закрыт). v1: profit_hwm, hurdle/mgmt=0, месяц.
- [ ] CRM-API оператора (CRUD клиент/счёт/договор, RBAC, аудит) + генератор периодов — todo (MFC-F3-next)
- [ ] Алерты Оператору в Telegram (событие commission_calculated уже пишется) — todo

## Ф4 — Клиентский портал (todo)
Цель: read-only портал + ровно две команды (ADR-0005).
- [ ] Портал: доходность/статус, без управления — todo
- [ ] PAUSE (мгновенно) + STOP_CLOSE (двойное подтверждение) через API ядра + аудит — todo

## Ф5 — Кузница-UI (todo)
Цель: библиотека профилей с паспортами (паспорт без OOS не существует).
- [ ] Библиотека профилей + паспорта (research/passport-spec) — todo
- [ ] UI Кузницы в консоли — todo

## Icebox (по одной строке, не в работу)
- Ансамбли: UI бота-дирижёра (труба заложена, ADR-0006; UI в v1 нет).
- Биржи OKX / BitGet — подключение после Bybit (трубы готовы, entities есть).
- Static IP Railway — пересмотр риска на mainnet-объёмах (ADR-0003).
- Идеи gbrain — для Исследований (summaries/gbrain).
- Railway Pro — не включать до Ф1–2 (решение D2).
- 🔩 TOTP Оператора — заготовка в MFC-001, ВКЛЮЧИТЬ до go-live (гейт, закон №2/угроза №2).
- 🔩 Rate-limit логина — до go-live (брутфорс, угроза №2; аудит login_failed уже пишется).
- Хвосты code-review MFC-001: request-id генерировать серверно/валидировать (#3);
  троттлить запись скользящего TTL (#5); флаг is_active у users (отключать клиента без удаления).
- Кокпит Пифагора (шов S9) — прокси через core к внутреннему порту; нужен ADR (COH7); v1 хватает телеметрии.
- pgbouncer перед кластером ботов — включить по росту флота (ADR-0007v2).
- Реконсиляция governance-доков (CLAUDE.md-перечень вики, WORKING_AGREEMENTS §2, root README о секретах) — за Куратором.
- Health-семантика never-reported инстанса (обзор MFC-003): дефолт `health='ok'` — ложно-зелёный для running без единого heartbeat; ввести `unknown`/`pending` или дефолт `stale` (решение Куратора, вместе с deploy-watch Ф2).
- 🔩 Картридж Пифагора scroll-past-window (ревью #1): телеметрия через окно build_monitor (recent-N 200/50) может пропустить старые trades/events при бэклоге>окна; сейчас — WARNING-детект. Полный фикс: курсорный direct-read из БД в обход окна. Гейт: до go-live/реальной торговли (в paper/demo некритично).
- 🔩 outbox-эскалация stop_close (разбор #3, M1): залип `stopping` N минут → алерт Оператору через outbox. Гейт: до go-live.
- 🔩 instance-токен: отзыв на teardown + чистка из `jobs.payload` (M2/N3, разбор #3), затем ротация. Гейт: до go-live.
- 🔩 governance-хвост аудита (разбор #2, MFC-004-b): аудит отклонённых операций оператора + прочие хвосты. Гейт: до go-live.
- 🔩 hardening до go-live: ingress-лимит тела телеметрии (N2); переименовать `job_longpoll_max_wait_seconds` в общий (N5).
- redelivery клиентской паузы pause/resume (M3, разбор #3): lease+redeliver ИЛИ видимость «залипших delivered». Гейт: до Ф4 (портал).
- Свёртка/ядро берут глобальный `get_sessionmaker` (игнорируя injected `settings.database_url`) — пред-существующее; per-app engine = рефактор db.py по нужде (обзор MFC-003).
