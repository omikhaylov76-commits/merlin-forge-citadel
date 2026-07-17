---
type: roadmap
title: Дорожная карта Merlin Forge Citadel
tags: [roadmap, phases]
updated: 2026-07-16
sources: [handoffs/HANDOFF_2026-07-10_session_1.md, _curator/DIRECTIVES.md#50]
---
# Roadmap: вехи → фичи

Оценка всего пути (Ф0→Ф5): 22–35 сессий. Статусы: todo / in-progress / closed.
**Единица работы с ~#29 — директива #NN Куратора** (`_curator/DIRECTIVES.md`), не roadmap-задача MFC-xxx;
roadmap отражает ФАЗЫ, задачи диктует директива (см. PROTOCOL.md). Ф0–Ф4 закрыты; активна Ф5 (Разведка→Кузница).

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

## Ф1 — Forge: флот на paper-bot (ЗАКРЫТА 2026-07-11)
Цель: конвейер платформы целиком, без денег — на бумажном боте. Достигнута (MFC-001…006 + обкатка Railway).
Остаточные [ ] ниже — гейты go-live (OPS13 reconcile) / поглощены Ф4 (консоль) / hardening, не блокируют закрытие.
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

## Ф3 — CRM + биллинг HWM (ЗАКРЫТА 2026-07-14)
Цель: клиенты, договорные параметры, комиссия % от прибыли по high-water mark. Достигнута (схема+движок HWM+API+периоды).
Остаточное [→] — Telegram-алерты, отложены Оператором (не блокер).
- [x] MFC-F3-1 CRM-схема (2026-07-14, main 532399c): таблицы clients + exchange_accounts (миграция 0005,
      CHECK fee/enum) + активация отложенных FK instances.client_id/account_id (ADR-0013 триггер) + бэкофилл
      сирот + bootstrap-родители + create_instance 404/400. CI зелёный. bot_type/profile FK — Ф5.
- [x] Финализировать ADR-0011 (модель HWM: месяц, cashflows, уровень счёта, сверка) — done (#27, accepted 2026-07-14)
- [x] Биллинг HWM + эталонные тесты (закон 8) — **done 2026-07-14 (main fb9983f)**: миграция 0006
      (contracts/billing_periods/cashflows + immutable-триггер + EXCLUDE overlap) + движок billing.py
      (compute_period + close_period, снапшот fee_pct, аудит commission_calculated). Адверс-ревью ×2
      (поймало critical money-баг порядка закрытия → закрыт). v1: profit_hwm, hurdle/mgmt=0, месяц.
- [x] CRM-API оператора (MFC-F3-2, main 7520463): CRUD clients/exchange_accounts/contracts + RBAC + аудит
      + v1-гейт договора (единый billing.v1_unsupported_reason для API и движка). Независимое ревью ×2
      (поймало critical C1 billing_period=quarter в обход гейта → закрыто). CI зелёный.
- [x] Генератор периодов (MFC-F3-3, main b026853, #31): миграция 0008 (billing_activated_at/terminated_at)
      + app/periods.py (активация с baseline MON3 + гарды / генератор-свёртка часового: месяц-от-активации-до-
      терминации, bit-в-bit, no backdating, валюта договора, пауза не пропускает, pending без фабрикации) +
      операторский API activate/terminate. Независимое ревью ×2 (латентный 🔴 двойного счёта депозитов закрыт).
- [x] Видимость застрявшего биллинга (#32 остаточный 🟢 #1, main 2397716): audit-событие
      period_generation_skipped (дедуп на границу+причину) + readout GET /v1/billing/stuck-accounts
      (нет equity/договора/смена валюты). Observability → само-ревью (#29). CI зелёный (167 тестов).
- [→] Алерты Оператору в Telegram (событие commission_calculated уже пишется) — ОТЛОЖЕНО Оператором
      (2026-07-15, «не к спеху, допилим потом»). Нужны токен бота @BotFather + chat_id (секрет, кладёт Оператор).
- Решения Куратора #32 (остаточные 🟢): пропорция при терминации НЕ нужна (v1 верно, % с фактической
  прибыли до даты); instance_id-роллап → Ф4/консоль; смена валюты договора → счёт pending (терминация+новый) — ok v1.

## Ф4 — Сборка консоли + портал (ЗАКРЫТА 2026-07-16: консоль live + демо-флот 5× в облаке, #36→#47)
Цель: настоящая консоль Оператора (React + shadcn/ui, слаш-дизайн) как ДИСПЛЕЙ поверх готового
бэкенда Ф3 (CRM/договоры/биллинг/периоды API — деньги в ядре, на фронте не дублируем) + клиентский
портал (отдельная поверхность, только свои данные, рецепт скрыт; ADR-0001/0005).
Источники (проект claude.ai «pifagor v8.1»): citadel/slash-console.html (вид), constructor-skeleton.html
(глубина), constructor-knobs-verified.md / console-*.md / kuznitsa-walkthrough.md / f3-crm-billing-spec.md
(логика/спеки). Стек: shadcn MCP (claude/shadcn-mcp-setup-for-coder.md), слаш-токены Desktop/дизайн/слаш/.
Каждый экран: пусто/грузится/ошибка + WCAG AA.
- [x] Первый шаг (main 1555553): дизайн-система (слаш-токены → тема Tailwind v4) + оболочка (сайдбар+хедер) +
      экран Обзор. console/ = Vite+React+TS, UI в паттерне shadcn (hand-rolled, без MCP). Проверено живьём
      (typecheck чист, dev-сервер, скриншот+роутинг). Обзор-агрегаты — демо-фикстуры (деньги в ядре, #32).
- [x] Экраны Флот / Сделки / Клиенты (main 0010c08): таблицы/плитки по макету, общие PageHead/Toolbar/Chip/MiniDd.
      Демо-данные — живые источники (инстансы/trades/CRM API) = бэкенд-подзадача.
- [x] Карточка клиента (main 382159a): KPI + боты/позиции + биллинг-периоды/движение/договор; плитки кликабельны, крошка-префикс.
- [x] Кузница · Конструктор профиля — ПОЛНАЯ глубина 7 разделов (main 932f333, #35): 1-4 Риск/Капитал/
      Исполнение/Режимы + 7 Служебные (🟢 23 крутилки, полки осн./эксп., ⚠, счётчик отличий, экспертный режим);
      5 Вселенная (🔵 таблица 16 монет mb1/mb2 эталона + 🟣 скринер disabled); 6 Политика входа (🟣 матрица ног,
      предпросмотр); блок Зафиксированная логика движка (🔵); OOS-паспорт. Метки зрелости 🟢живое/🔵read-only/🟣Ф5.
      Логика движка read-only в ядре; фикстуры, live-эндпоинт вселенной = TODO.
- [x] Кузница · Разведка (kanban скаута) + Профили (библиотека рецептов) (main 98b8008) — по макету, демо-данные.
- [x] Хвост #34 (main 67b8e6b): Отчёты (архив) · Тревоги (2 семьи/severity/табы) · Настройки (8 подразделов) ·
      Портал клиента (отдельная read-only поверхность, обе команды с модалом-«распиской», рецепт скрыт). ConfirmModal (danger).
- **Консоль укомплектована — 11 экранов** (демо-данные, деньги в ядре).
- [x] Бэкенд-хвост Ф4 (#36): (1) CI-джоба фронта typecheck+build (db0dd90); (2) агрегат-эндпоинт флота
      `GET /v1/fleet/overview` — боты/клиенты/AUM/closed-net/комиссия, readout (273f2a9, +4 теста);
      (3) экран логина Оператора + гейт RBAC + выход (699eb74). Проверено живьём + CI зелёный.
- [ ] Подключить Обзор к живому `/v1/fleet/overview` (слезть с фикстур) — после дизайн-прохода Куратора.
      Помощники Кавалл/Архимед — отдельной фазой.
- Помощники Кавалл + Архимед — отдельной фазой ПОСЛЕ консоли (#32/#34), сейчас только витрина в Настройках.

## Ф5 — Разведка → Кузница (in-progress, старт #49–#50 2026-07-16)
Цель: сначала живая **Разведка** (реальные сетапы скаута на консоли — график сетапа + сортировка), затем
**Кузница** (библиотека профилей с паспортами; паспорт без OOS не существует). План дуги Разведки —
progress/f5-scout-channel.md. Платформа рынок НЕ сканирует — принимает СНИМКИ от бота (ADR-0016).
- [x] #49 Рекон Разведки: поля скаута / канал данных / данные графика — сверены кодом (отчёт в QUEUE) — 2026-07-16
- [x] #50 ADR-0016 + scout-канал Контракта v1 (схема `telemetry-scout` + бамп v0→v1 + sync-гвозди; 0 строк в vendor/) — принят Куратором построчно, merged 1d7e91c, CI зелёный — 2026-07-16
- [x] #51 Изоляция картриджа: fail-closed `SCOUT_ENABLED`-гейт + отдельная `scout.db` (DB_PATH) + супервизор (liveness+RSS, рестарт только скаута) в start.sh + хвост A баннер — принят построчно, merged f9988d6, CI зелёный — 2026-07-16
- [x] #52 Труба scout целиком: ручка `POST /v1/telemetry/scout` + таблица/миграция 0009 (replace-снимок) + readout + Pydantic-зеркало + адаптер scout_reader/mapper/push + сквозняк локально — merged fa3f1b5, CI зелёный — 2026-07-16
- [x] #53 Живой экран Разведки: Scout.tsx на live-readout, канбан 4 колонки + карточка (%-до-входа/спарклайн) + деталь-график Lightweight Charts (свечи + A→B/Fib/стоп + слой ордеров) + 4 плашки + 3 пустых состояния + развёртка графика — принят построчно (код+рендер), CI зелёный — 2026-07-16. **Дуга Разведки #49–#53 завершена.**
- [x] С7-1 воздух графика (rightOffset — правило показа на ВСЕ графики) + ТФ-переключатель 4h|1h (доска tf-aware, бейдж ТФ, дубли убраны) — только console/src, merged 391aa24/c1a15b7, задеплоено в облако (по слову Оператора), tsc+build+code-review зелёные — 2026-07-16. progress/s7-1-tf-air.md
- [x] С7-2а скринер офлайн-ядро (импульс-метрика) + живой прогон отчёт-only — merged (d95e2f1/5d396c6), 0 vendor — 2026-07-16
- [x] С7-2б/С7-3 скринер ЦЕЛИКОМ: ядро (миграция 0010, команда screener_run, push, readout) + картридж (обработчик, отдельный процесс, гейт SCREENER_ENABLED деф.ВЫКЛ) + консоль (экран Скринер) — merged e77f479/5c15d27, задеплоено (ядро+Галахад+консоль), сквозной прогон вживую (кнопка→Галахад→таблица) — 2026-07-17
- [ ] Кузница: библиотека профилей + паспорта (OOS) + UI + полный залок эталона «Малыш Мерлин» (ADR-0014) — todo (после Разведки)

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
