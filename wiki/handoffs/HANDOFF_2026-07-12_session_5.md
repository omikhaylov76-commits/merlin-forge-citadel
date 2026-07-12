# HANDOFF: Session 5 → Session 6

**From:** Session 5 (Инженер, Claude Code) · **Date:** 2026-07-12
**Веха:** **Ф2 ЗАКРЫТА** — картридж Пифагора живёт в облаке, сквозняк облако-в-облако · **Следующее:** «Малыш Мерлин» (#11)

---

## 1. Состояние
**Ф2 ЗАКРЫТА (миссия F1→F2 выполнена).** Платформа гоняет копию Пифагора как первый боевой картридж
ЦЕЛИКОМ В ОБЛАКЕ (Railway), в безопасном режиме (Bybit demo, торговля выключена).
- **Облако (Railway-проект `merlin-forge-citadel`), всё живо:**
  - **Postgres** (SUCCESS, эфемерный — без volume пока).
  - **Ядро** `mfc-core` — публичный `https://core-production-429b.up.railway.app` (healthz/readyz 200,
    БД по приватному DNS `postgres.railway.internal`, миграции Alembic на старте, scheduler тикает).
  - **Картридж** `mfc-inst-pifagor-demo` — worker Пифагора в DEMO (`api-demo.bybit.com`, 16 монет,
    `LIVE_TRADING_ENABLED=0`, `BYBIT_DEMO=1`); адаптер шлёт телеметрию ядру по приватной сети.
- **Доказано облако-в-облако** (аудит ядра): heartbeat `204` · equity/events `202` (непрерывно) +
  команда **pause**: `enqueue 201 → command_delivered → command_ack`. Критерий #15 выполнен.
- **main @ `3da1a3c`** (pushed, в синке, CI зелёный). Все образы в ghcr (public): `mfc-core:main`,
  `mfc-pifagor-cartridge:main` (+`:sha-*`). Ветка task/f2-pifagor-cartridge слита и удалена.
- **Тесты:** core 84+ (вкл. bootstrap) · orchestrator 23 · paper-bot 22 · **pifagor-cartridge 70**
  (client 4xx / mapper / bot / parity(реальный build_monitor) / schema-conformance). CI на main зелёный.

## 2. Сделано в сессии
- **Адаптер картриджа** `bots/pifagor-cartridge` (read-only, ADR-0001): recon-2 → Вариант A #10
  (телеметрия через вендоренный `dashboard/viewmodel.build_monitor` → цифры == родной дашборд); команды →
  `PAUSE_ENABLED`/killswitch; **4xx-классификация + backoff + 413-split (#6/#7)**. 70 тестов, независимое
  адверсариальное ревью (агент) — findings #1–#5, все закрыты/задокументированы.
- **Облачная сборка (#12):** CI-джобы `pifagor-cartridge`+`cartridge-image`+`core-image` → образы в ghcr;
  **локальный Docker убран** с машины Оператора.
- **Слияние Ф2-адаптера в main** (4ef05ab, --no-ff).
- **Облако (#15/#17):** починен битый `RAILWAY_PROJECT_ID` в orchestrator/.env; создан проект
  `merlin-forge-citadel` (projectCreate по API); Dockerfile ядра + bootstrap (`core/app/bootstrap.py`:
  оператор + демо-инстанс/instance-токен из env); подняты Postgres+ядро+картридж; полный сквозняк.
- Вики: log/roadmap/progress/index/QUEUE обновлены; руководство `wiki/runbooks/pifagor-cartridge-deploy.md`.

## 3. Решения/находки сессии (в DIRECTIVES/QUEUE/log)
- **#10 Вариант A** (build_monitor faithful) · **#12** Docker в облаке · **#15** в облако И ЯДРО, И картридж ·
  **#16** demo-ключи из `_curator/secrets.env` · **#17** создать проект + починить .env.
- **RailwayDriver неполон:** `serviceCreate` создаёт сервис, но деплой образа запускает
  **`serviceInstanceDeploy(serviceId, environmentId)`** — этого в драйвере НЕ было. Провижн вёл через GraphQL
  (`serviceCreate`+`serviceInstanceDeploy`+`variableUpsert`+`serviceDomainCreate`). **Railway CLI 5.26 токен
  НЕ принимает** (whoami/list Unauthorized) — только GraphQL API.
- **Демо-инстанс сеян bootstrap-обходом** (не боевым `create_instance`→оркестратор): `create_instance`
  возвращает `{id,status,deploy_job_id}`, instance-токен НЕ отдаёт (он в job для оркестратора). Для сквозняка
  задал instance-токен через env (секрет-стор). Боевой путь — оркестратор.

## 4. Секреты (НИКОГДА в git/лог/чат — закон №2)
- `orchestrator/.env` (gitignored): `RAILWAY_API_TOKEN` + `RAILWAY_PROJECT_ID` (починен, UUID проекта) + DRIVER.
- `_curator/secrets.env` (gitignored): demo-ключи Bybit `BYBIT_API_KEY/SECRET` (subaccount merlinFC1) + safe-флаги.
- **В env облачных сервисов Railway** (не в git): у ядра — `DATABASE_URL`, `BOOTSTRAP_OPERATOR_EMAIL/PASSWORD`
  (operator@mfc.local + сгенерённый пароль), `BOOTSTRAP_INSTANCE_ID/TOKEN`; у картриджа — `MF_INSTANCE_ID/TOKEN`,
  `MF_CORE_URL=http://core.railway.internal:8000`, `BYBIT_API_KEY/SECRET`, safe-флаги.
- Пароль оператора + instance-токен я сгенерил в скриптах (память) и вписал в env ядра/картриджа; локально не
  сохранял. **Достать при нужде:** GraphQL `variables(projectId, environmentId, serviceId)` по сервису `core`.
- ⚠️ Ранее в ЭТОМ чате Оператор вставил demo-ключи прямо в переписку (я их не использовал) — рекомендовал
  пересоздать на Bybit. Проверь, пересозданы ли; боевые ключи — только по отдельному go-live.

## 5. Как управлять облаком (скрипты сессии — в /private/tmp scratchpad, в новой сессии их НЕТ)
Провижн/деплой вёлся ad-hoc python+GraphQL (httpx, токен из orchestrator/.env, `trust_env=False`). Паттерны:
- Найти env+сервисы: `project(id){ environments{edges{node{id}}} services{edges{node{id name}}}}`.
- Задеплоить образ: `serviceCreate(input:{projectId,name,source:{image},variables})` → `serviceInstanceDeploy(serviceId,environmentId)`.
- Переменные: `variableUpsert(input:{projectId,environmentId,serviceId,name,value})` (аддитивно) → redeploy.
- Логи: `deploymentLogs(deploymentId, limit)`. Статус: `deployments(first:1, input:{serviceId,environmentId}){edges{node{status}}}`.
- ⚠️ Railway лимитит частые деплои («rate limit exceeded») — ставь паузы между `serviceInstanceDeploy`.
- **Снести демо-сервисы (если надо):** `serviceDelete(id)` для core/postgres/mfc-inst-pifagor-demo (compute hobby капает мало).

## 6. Следующий шаг (конкретно) — «Малыш Мерлин» (#11, DIRECTIVES)
Порядок Куратора: после Ф2 → «Малыш Мерлин». **Часть A можно СЕЙЧАС (не зависит от картриджа):**
- **A. Полный замороженный АРХИВ Пифагора @b75bd17 в ДВУХ местах:** (1) неснимаемый annotated git-тег
  `malysh-merlin/v8.3-b75bd17` + GitHub release НА РЕПО pifagor-v81 (не трогать код, только тег); (2)
  `git archive b75bd17` → `malysh-merlin-v8.3-b75bd17.tar.gz` как release-ассет Цитадели ИЛИ в `reference/`
  (git-LFS если в дерево); SHA256 архива в `reference/README`. Это включает и `engine/` (эталон), который в
  рантайм-картридж не тащили (#13).
- **B. Залоченный профиль-эталон:** извлечь дефолтную конфигурацию Пифагора @b75bd17 в замороженный
  `reference/malysh-merlin-profile-v8.3.json` (захват дефолтов; паспорт — реальный трек-рекорд). Полный
  залок-в-UI — Ф5.
- **C/D. Версионирование снимка + ADR-0014** «Малыш Мерлин — эталон-нулевой-пациент».
- Границы: pifagor-v81 не править (только тег/архив-чтение); реальные ключи/торговля — СТОП до go-live.

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -1 main` = `3da1a3c`; в синке с origin; дерево чистое.
- [ ] Прочитать `_curator/DIRECTIVES.md` (разборы #10–#17) + `_curator/PROTOCOL.md`; QUEUE — «Ф2 закрыта» + хвосты.
- [ ] CI на main зелёный (core+orchestrator+paper-bot+pifagor-cartridge+cartridge-image+core-image).
- [ ] Облако живо: `curl https://core-production-429b.up.railway.app/healthz` = 200. Картридж шлёт телеметрию
      (аудит ядра: `deploymentLogs` сервиса core → telemetry 204/202). Проект Railway `merlin-forge-citadel`.
- [ ] Секреты: `orchestrator/.env` + `_curator/secrets.env` gitignored, НЕ печатать. Demo-ключи — только demo.
- [ ] `bots/pifagor/vendor/` (68 файлов, +dashboard/viewmodel) и `bots/pifagor-cartridge/` на месте.
- [ ] Тесты (нужен Docker+dev DB — на момент хэндоффа docker daemon был ВЫКЛЮЧЕН у Оператора; поднять для core):
      core `cd core && DATABASE_URL=… .venv/bin/pytest -q`; pifagor-cartridge `.venv/bin/pytest -q` → 70.
- [ ] QUEUE-хвосты (go-live): бэкпорт serviceInstanceDeploy в RailwayDriver; Postgres volume; scroll-past-window fix.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 5 → Session 6.
