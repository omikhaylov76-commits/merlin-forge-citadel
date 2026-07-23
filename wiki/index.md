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
- [HANDOFF_2026-07-18_session_12](handoffs/HANDOFF_2026-07-18_session_12.md) — **🏁 S8 ВЕХА 1 ЗАКРЫТА ВЖИВУЮ** (Борс `cd8d0534` в динамике на облаке, dry-run; стек 7 живых монет из печки, 0 ордеров). Слой 3 (канал критериев ADR-0020 + консоль) + аудит 5 линз (showstopper state↔status починен + вендор-тест) + триппвайр Вехи 2 — в main. Деплой узкими rw_deploy_bors/core (gitignored). main @ 0eb72c9. Дальше: Веха 2 (пин+торговля, гейт Оператор+Куратор).
- [HANDOFF_2026-07-21_session_13](handoffs/HANDOFF_2026-07-21_session_13.md) — **S8 «наведение порядка»**: verified-график сделки + кнопка скана на карточке + СВОЯ Postgres Борсу (per-bot, откл. ADR-0007) + 2 живых бага (422-журнал, scout.db-пин). main @ 398b397. Лимит Куратора исчерпан — развилки в QUEUE.
- [HANDOFF_2026-07-22_session_14](handoffs/HANDOFF_2026-07-22_session_14.md) — **S8 горн+самоход ОТГРУЖЕНЫ** (Куратор вернулся, ADR-0021, 2-я дельта генома; merged+deployed+живая сверка: горн подтверждён, самоход виден) + Postgres всему торгующему флоту + единая Разведка (дизайн: селектор бота, превью=А, нагрузка Bybit развенчана). main @ 786bd44.
- [HANDOFF_2026-07-22_session_15](handoffs/HANDOFF_2026-07-22_session_15.md) — **🏁 S8 F-warm-button ОТГРУЖЕН + ЖИВАЯ ПОСТАНОВКА** (ADR-0022 команда `warm_apply` «Поставить» валидный сетап, 0-vendor; Оператор нажал на 1INCH → Борс поставил демо-ордер, п.1/п.2 приёмки закрыты, **эталон Борс ДОСТРОЕН**; миграция 0015) + единая Разведка (дизайн: ТФ от бота, сайдбар Конструктор-первым) + мультивыбор/UX-нюансы. Разведка/Кузница разблокированы Куратором; 3 пункта на подпись. main @ c10bf7e.
- [HANDOFF_2026-07-22_session_16](handoffs/HANDOFF_2026-07-22_session_16.md) — **S8 Единая Разведка + engine-источник (F-lookahead ВЫЛЕЧЕН) + 3 консольные доводки.** Правда движка per-coin (поле engine telemetry-scout, доска-по-вердикту, merge c4e199a, Куратор принял) · RED-фикс scout-пуша (доска висла) + авто-обновление · engine-источник (вселенная от warm.classify по scout_list, не скаут-курации; DYNAMIC_SOURCE env; merge 18248b7) — Борс берёт placeable (ENA/KAITO вернулись, 7 vs 2 из 13) · бары per-coin=проводка volnorm у Куратора · 3 доводки консоли (судьба warm + скан-индикатор, c07340e). main @ c6a05d1.
- [HANDOFF_2026-07-23_session_17](handoffs/HANDOFF_2026-07-23_session_17.md) — **S8 per-coin бары ОТГРУЖЕНЫ+СВЕРЕНЫ (порция №1 канона) + КАНОН ОЧЕРЕДИ Куратора (5 порций) + 4 консольные доводки + диагноз cap=16.** Проводка volnorm-баров merged `2c01f8e`, деплой Борса, живая сверка (differentiated: 1INCH 1.75/3, WLFI 2.5/4.25) · Куратор: КАНОН 5 порций (бары✅→прогрев held→Сигнальный журнал→Конструктор→Теневой клиент) · консоль: warm-пометка переживает навигацию + унификация Разведки, точность цены графика, «греется»+сквозняк, откат «греется без чек-бокса» · cap=16 диагноз (движок, не баг) → развилка Куратору. main @ 2dbe7b9.
- [progress/s8-dinamo-bliznec-v1](progress/s8-dinamo-bliznec-v1.md) — S8 Веха 1 (dry-run): разъём генома + провайдер + канал критериев + деплой Борса. Слои 1–4 ✅, закрыта вживую.
- [progress/s8-dinamo-bliznec-v2](progress/s8-dinamo-bliznec-v2.md) — S8 Веха 2 (демо-ордера через пин позиций): план, ждёт подписи Куратора + гейт Оператор+Куратор на LIVE_TRADING=1.
- [progress/s8-bors-gorn-samohod](progress/s8-bors-gorn-samohod.md) — S8 Борс: горн (ручной warm) + самоход (периодический warm по SIGNAL_TF); разведка+план+аудит, на подпись (развилка геном/0-vendor).
- [ADR-0017 — Набор Оператора (НАБОР-1): витрина+хранение отмеченных сетапов](decisions/0017-basket-nabor-1.md)
- [progress/nabor-1 — корзина сетапов: ядро+консоль, ничего не торгует](progress/nabor-1.md)
- [0018](decisions/0018-scout-settings-from-core.md) — канал настроек дозора из ядра (scout_settings): ядро=истина, картридж boot-fetch+рестарт скаута; движко-скоуп на канал не пускаем.
- [0019](decisions/0019-coins-universe-socket-genome.md) — разъём вселенной монет в геноме (COINS_CONFIG_PATH, S8): амендмент Закона 6/ADR-0016 «0 vendor» + инвариант живого генома + реестр дельт + страж-дрейфа CI; гейт Вехи 2 двухчастный.
- [0020](decisions/0020-dynamic-settings-from-core.md) — канал критериев Динамики из ядра (dynamic_settings, S8): зеркало дозора, СВОЙ канал (Закон 3); D1 JSON-файл+живьё (провайдер foreground), re-fetch убирает dynamic_apply; политика капа на сжатие.
- [0021](decisions/0021-warm-rhythm-socket-genome.md) — разъём warm-ритма в геноме (S8): периодический auto_eligible-подхват на границе SIGNAL_TF (флаг WARM_EACH_CYCLE) + горн (интент WARM_AUTO_NOW через scan_now); 2-я санкц. дельта, страж-дрейфа расширен.
- [0022](decisions/0022-f-warm-button-warm-apply-command.md) — F-warm-button: команда Контракта `warm_apply` («Поставить» валидный сетап, вкл. reanchored) — Оператор-only (портал не видит, Закон 5), 0-vendor (интент WARM_APPLY→существующий maybe_warm/_warm_one_button), single-shot; добивает эталон Борса (п.1/п.2 приёмки).
- [0023](decisions/0023-concurrency-cap-24-dynamic.md) — потолок конкуренции 24 для динамик-характера (Борс, демо): 3-я санкц-дельта генома (сдвиг границы `hi:16→24`, движок не тронут); честная пометка + ре-бэктест = техдолг.
- [progress/s8-razvedka-unified](progress/s8-razvedka-unified.md) — Единая Разведка (подпись Куратора 22.07): адаптер warm.classify per-coin → поле `engine` telemetry-scout → доска-по-вердикту; план 4 слоёв.
- [progress/s8-dynamic-engine-source](progress/s8-dynamic-engine-source.md) — F-lookahead v3: вселенная движка ОТ ДВИЖКА (placeable-отбор по scan_list, DYNAMIC_SOURCE), план+аудит 5 линз, ждёт подписи.
- [progress/s8-per-coin-bars](progress/s8-per-coin-bars.md) — проводка per-coin volnorm-баров движку (mb1/mb2/bar_source из scout_list вместо плоского 2.0/3.5; sticky+held-заморозка+refresh-ритм). Подпись Куратора, merged `2c01f8e`; ЖИВАЯ СВЕРКА прошла (differentiated в карточке), деплой Борса+консоли сделан.
- [progress/s8-progrev-held](progress/s8-progrev-held.md) — порция №2: boot-шаг `prewarm_held` пишет coins.json из held ДО старта движка (v1 «правка tick» не работал — разведка) → окно неведения закрыто. merged `66d23ca`, сверка: стек 5/5 held (не дефолт-16).
- [progress/s8-cap-24](progress/s8-cap-24.md) — ADR-0023 CONCURRENCY_CAP 16→24 (Борс, демо): 3-я санкц-дельта генома, страж-дрейфа, тест vs вендор; merged `00942f1`, деплой+сверка `cap=24` жив.
