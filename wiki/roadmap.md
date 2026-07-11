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
- [~] Обкатка Railway на живом paper-bot (допущение №3): **deployability ✅ 2026-07-11** — Railway CLI
      собрал наш Dockerfile и запустил процесс картриджа (изолированный проект, прибран). Осталось:
      полная сверка GraphQL-драйвера (образ в реестре + RAILWAY_API_TOKEN + прогон orchestrator) — runbook.
- [ ] 🚧 MFC OPS13 reconcile сирот: свёртка часового сверяет instances↔сервисы `mfc-inst-*`, гасит
      сирот (разбор Куратора #2, вариант A). **Гейт: ДО Ф2** (до первого реального деплоя) — todo
- [ ] Консоль Оператора: минимальный флот-дашборд (после мокапа) — todo

## Ф2 — Пифагор-картридж (todo)
Цель: первый боевой движок за Контрактом, без правок pifagor-v81.
- [ ] Recon: storage/db.py и dashboard/viewmodel.py — проверить допущение «обёртка без правок репо» — todo
- [ ] Обёртка-образ: адаптер телеметрии + heartbeat ≤60с отдельным циклом — todo
- [ ] Конверт-шифрование ключей биржи end-to-end (ADR-0004) + тесты — todo

## Ф3 — CRM + биллинг HWM (todo)
Цель: клиенты, договорные параметры, комиссия % от прибыли по high-water mark.
- [ ] CRM-модель: клиент → договор → инстансы — todo
- [ ] Финализировать ADR-0011 (модель HWM: cashflows, уровень счёта, сверка) ДО кода биллинга — todo
- [ ] Биллинг HWM + обязательные тесты (закон 8, формула из ADR-0011) — todo
- [ ] Алерты Оператору в Telegram (runbooks/alerts) — todo

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
- 🔩 outbox-эскалация stop_close (разбор #3, M1): залип `stopping` N минут → алерт Оператору через outbox. Гейт: до go-live.
- 🔩 instance-токен: отзыв на teardown + чистка из `jobs.payload` (M2/N3, разбор #3), затем ротация. Гейт: до go-live.
- 🔩 governance-хвост аудита (разбор #2, MFC-004-b): аудит отклонённых операций оператора + прочие хвосты. Гейт: до go-live.
- 🔩 hardening до go-live: ingress-лимит тела телеметрии (N2); переименовать `job_longpoll_max_wait_seconds` в общий (N5).
- redelivery клиентской паузы pause/resume (M3, разбор #3): lease+redeliver ИЛИ видимость «залипших delivered». Гейт: до Ф4 (портал).
- Свёртка/ядро берут глобальный `get_sessionmaker` (игнорируя injected `settings.database_url`) — пред-существующее; per-app engine = рефактор db.py по нужде (обзор MFC-003).
