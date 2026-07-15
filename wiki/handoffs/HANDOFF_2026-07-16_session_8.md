# HANDOFF: Session 8 → Session 9

**From:** Session 8 (Инженер, Claude Code) · **Date:** 2026-07-16
**Веха:** **#47 — демо-флот 5× «Живой V3» в облаке. Персиваль в demo-LIVE (FC1, $20K), 4 припаркованы dry-run.**
Дальше: поймать первый демо-ордер Персиваля (з.4-доказательство) → выводить остальных 4 live по одному (Кузница/Ф5).

---

## 1. Состояние (что работает в облаке)
Railway-проект `merlin-forge-citadel`: **ядро** (`core-production-429b.up.railway.app`, схема 0008) + **консоль**
(`console-production-f533.up.railway.app`, живые Обзор/Клиенты/Флот/сводка) + **5 картриджей** `mfc-inst-*` + Ф2-сирота.
- **Персиваль**: `running`, **demo-LIVE** (LIVE_TRADING_ENABLED=1), субсчёт **merlinFC1 ~$20K**, конфиг **Живой V3**,
  kill −70%. **0 ордеров** — ждёт 4h-сетап (норма, «на связи»). equity $19986 (не двигался).
- **Галахад/Борс/Ланселот/Гавейн**: `running` **dry-run** (LIVE=0), «припаркованы». Сейчас на ОБЩЕМ ключе (equity
  ~$166K показывают — их субсчёта FC2–FC5 НЕ привязаны, deferred по #47). Их $20K привяжутся при выводе каждого live.
- Оба ghcr-образа (`mfc-core`, `mfc-pifagor-cartridge`) **PUBLIC** — окно деплоя (ADR-0015; private требует Pro=D2).
- **main @ `0bc8d10`**, в синке с origin, дерево чистое. Незакоммиченного кода НЕТ.

## 2. Сделано в сессии (#44→#47 з.4; всё в main, CI зелёный)
- **#44:** доказательства Шага A в репо (`reference/perceval-configdiff-b75bd17.json` + транскрипт S4 в progress); pifagor.db → .gitignore.
- **з.1 (стек в облако):** передеплой ядра свежим main (миграции 0004→0008, `/fleet/overview` жив) + **консоль публичным Railway-сервисом** (nginx: SPA + прокси `/api`→ядро; `railway up`).
- **Драйвер (влит):** RailwayDriver + `registryCredentials` + `serviceInstanceDeploy` + резолв environmentId. **ADR-0015** (модель деплоя картриджей: демо=публичный образ / go-live=приватный+cred на Pro/Docker; C отклонён).
- **Bootstrap ядра:** `seed_orchestrator` (токен аренды jobs) + синк пароля оператора из env. **Оркестратор:** вливка demo-ключей Bybit в env деплоя (#16, `deploy_env_extra`).
- **#46/#47 з.2:** Персиваль live в облаке dry-run (онбординг через API ядра → оркестратор арендует job → картридж на Railway → телеметрия облако-в-облако). **Консоль на живьё:** Клиенты/Флот/сводка + новый `GET /v1/fleet/instances`.
- **#47 флот-V3:** `reference/fleet-live-config.json` (23 крутилки Живого V3, KILLSWITCH_DD=0.70) + развёрнуто **5 картриджей dry-run** (Персиваль пересажен с эталона на V3 + 4 новых) + `reference/fleet-v3-configdiff.json` (**drift=[]**, живой лог `knobs(eff) risk 2.5/cap 16`). Куратор **принял з.4**.
- **#47 з.4 флип (корректировка Оператора):** **только Персиваль → demo-LIVE**, 4 припаркованы. Балансы всех 5 субсчётов → $20K (Оператор); Персиваль паузнут→сверен FC1=$20K→resume (чистый старт).

## 3. Решения сессии
- **ADR-0015** — модель деплоя картриджей (оформлен, wiki/decisions). Триггер пересмотра: Pro/go-live.
- **База флота = «Живой V3 (demo)»** (снимок живого V3-конфига Пифагор-кодера), НЕ эталон. Эталон «Малыш Мерлин» @b75bd17 заморожен (ADR-0014). Kill −70% для demo-песочницы клиента №0 (клиентам −50%).
- **Приватный образ на Railway требует Pro** (живой API) → на hobby (D2) деплой только с публичным образом (окно). См. [[railway-pro-private-image-blocker]].
- **Пауза перед сменой баланса:** Персиваль паузили (PAUSE_ENABLED, держит позиции), чтобы не войти на непересчитанном балансе → resume после $20K.

## 4. Код / доступы (секретов тут НЕТ)
- main @ `0bc8d10`, чист. Ветки задач влиты и удалены (`task/railway-private-pull`, `task/console-*`).
- **orchestrator/.env** (gitignored): DRIVER=railway, CORE_API_URL=облако, ORCHESTRATOR_TOKEN, RAILWAY_*, ghcr-креды УБРАНЫ (публичный образ), BYBIT-ключи нормализованы: `BYBIT_API_KEY__<SLUG>` (PERSIVAL/GALAHAD/BORS/LANCELOT/GAWAIN) + FC1 unnamed-дефолт. Мапинг: Персиваль→FC1 … Гавейн→FC5 (подтверждён Оператором).
- **Облачный вход Оператора:** `o.mikhaylov76@gmail.com`; пароль — в Railway core env `BOOTSTRAP_OPERATOR_PASSWORD` (сменить через env+передеплой, bootstrap синкает). Локально был в `/tmp/cloud_pw.txt` (эфемерно). **В хэндофф пароль НЕ пишем.**
- IDs Персиваля (облако): client `09ebd476…`, instance `a6df714f…`, cartridge svc `b96bd5ca…`. Env id `c3901a24…`.

## 5. Открытые вопросы
- **Первый демо-ордер Персиваля** (монета) — ещё не было; поймать (монитор был, остановлен на переход) → зафиксировать в репо (з.4-доказательство, скрин Флота).
- **Вывод 4 припаркованных live** — по одному через Кузницу (Ф5), с привязкой их FC2–FC5 ($20K) + LIVE=1 (Оператор подтверждает ключ каждого при выводе).
- **#48 чистка синтетики** (Ф2-сирота `mfc-inst-pifagor-demo` + фронт-фикстуры Сделки/Профили/Тревоги) — ПОСЛЕ флота.
- **go-live хвост:** сузить ghcr-PAT до `read:packages` (сейчас repo+write); образы → private + Pro.
- **Косметика:** `bots/pifagor-cartridge/start.sh:9` печатает ХАРДКОД «(dry-run demo)» независимо от LIVE — путает лог.
- **TZ-хрупкость** `test_periods::test_stuck_readout_and_skip_audit_once` (локаль +03:00 vs UTC; CI зелёный).

## 6. Следующий шаг (конкретно)
Поймать **первый демо-ордер Персиваля** (на какой монете вошёл) → зафиксировать в репо как з.4-доказательство.
Затем ждать Оператора/Куратора по выводу следующего бота (Галахад…) live — привязать его субсчёт + LIVE=1.

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -1` = `0bc8d10`; в синке; дерево чистое.
- [ ] Прочитать `_curator/DIRECTIVES.md` низ: «#47 з.4 ПРИНЯТО» + «КОРРЕКТИРОВКА ФЛИПА: только Персиваль live».
- [ ] Облако живо: `curl core-production-429b.up.railway.app/healthz`=200; консоль-логин грузится.
- [ ] Персиваль: `running`, demo-LIVE, equity ~$20K — **проверить, не появился ли первый ордер** (equity сдвинулся?).
- [ ] 4 припаркованных: `running` dry-run (LIVE=0), НЕ трогать без директивы.
- [ ] Оба ghcr-образа `mfc-core`/`mfc-pifagor-cartridge` — PUBLIC (иначе Railway не перетянет на hobby).
- [ ] `reference/fleet-live-config.json` (V3, KILLSWITCH_DD=0.70) + `fleet-v3-configdiff.json` (drift=[]) в дереве.
- [ ] Секреты gitignored (`_curator/`, `orchestrator/.env`); в лог/чат/хэндофф не печатать.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 8 → Session 9.
