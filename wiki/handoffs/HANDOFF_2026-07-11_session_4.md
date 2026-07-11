# HANDOFF: Session 4 → Session 5

**From:** Session 4 (Инженер, Claude Code) · **Date:** 2026-07-11
**Веха:** Ф1 ЗАКРЫТА · Ф2 начата (снимок Пифагора вендорен) · **Следующее:** адаптер картриджа Пифагора

---

## 1. Состояние
**Ф1 «Forge на paper-bot» технически закрыта** — весь конвейер платформы слит в main, запушен, CI зелёный:
оператор заводит инстанс → оркестратор деплоит (Railway-драйвер подтверждён вживую) → бот шлёт телеметрию
и честно исполняет kill-switch. **Ф2 начата:** снимок Пифагора `b75bd17` вендорен в `bots/pifagor/vendor/`
(ветка `task/f2-pifagor-cartridge`, WIP — адаптера ещё нет).
- Работает (main): FastAPI-ядро (auth/часовой/stale-скан) · jobs-транспорт S3 (аренда/ack/fencing) ·
  оркестратор + InfraDriver (Fake/Docker/**Railway — GraphQL подтверждён на живом API**) · приём телеметрии
  S4 (dedup/ts-skew) · команды S4 (липкий stop_close) · эталонный картридж paper-bot.
- **Тесты:** core 81 · orchestrator 23 · paper-bot 22 (все зелёные, CI на main зелёный).

## 2. Сделано в сессии
- **Автономный режим Куратора** настроен: указатель на `_curator/DIRECTIVES.md` в CLAUDE.md, `_curator/` в
  .gitignore, память обновлена. Режим: merge+push автономны, «дальше» не спрашивать, стоп только на гейте Ф2.
- **MFC-004** оркестратор + InfraDriver (шов S3) — merged `ed18bb9`. Ревью: блокер ack-переклассификации закрыт.
- **MFC-005** core-сторона Контракта Бота (шов S4) — merged `99942f8`. Ревью: M1/M2/M4/N1/N6 закрыты.
- **MFC-006** эталонный картридж paper-bot — merged `0baacb9`. Ревью: M1/M2 (equity/идемпотентность) закрыты.
- **Обкатка Railway:** deployability (CLI собрал+запустил образ) + **RailwayDriver GraphQL подтверждён на
  живом API** (deploy→status→destroy) + фикс `trust_env=False` — merged `f2d6bfe`. Тестовые проекты удалены.
- **Ф2 kickoff:** снимок Пифагора `b75bd17` (свежий клон github, не из локали) вендорен НАЧИСТО в
  `bots/pifagor/vendor/` (66 файлов, живой субсет по реальному графу) — ветка `task/f2-pifagor-cartridge`.

## 3. Решения сессии (в DIRECTIVES/QUEUE/log, не как новые ADR)
- **Автономный режим** (DIRECTIVES #5): цикл MFC-xxx автономен вкл. merge+push; не спрашивать «дальше»;
  жёсткий стоп на участке — только ГЕЙТ Ф2 (коммит снимка Пифагора) + реальные ключи/деньги.
- **M2 MFC-005:** машинные токены (instance/orchestrator) непротухающие (даунтайм core не запирает флот) —
  одобрено Куратором #3. **M1:** stop_close error не терминален (липкость до ok) — одобрено #3.
- **RailwayDriver `trust_env=False`** — обкатка показала зависание httpx на netrc/CA из env.
- **Вендор Пифагора:** `engine/` (эталон-бэктест) ВЫКИНУТ, `app/`+`state/` ДОБАВЛЕНЫ — по реальному графу
  импортов (отклонение от эвристики Куратора #7, вынесено в QUEUE на разбор).

## 4. Код
- **Ветка `task/f2-pifagor-cartridge`** @ `07b4513` (pushed, в синке с origin) — вендор снимка Пифагора.
- **main** @ `7af4d09` (pushed, в синке) — вся Ф1 + Railway обкатка + Ф2 kickoff-доки.
- **Незакоммиченного НЕТ**, дерево чистое. Ф2-ветка НЕ слита в main (WIP: картридж не функционален без адаптера).
- Фича-ветки MFC-004/005/006 и task/railway-shakedown слиты и удалены.

## 5. Открытые вопросы
- **Куратору (QUEUE):** вендор-отклонение (engine выкинут / app+state добавлены — подтвердить); отложенные
  находки MFC-004/005/006 разложены по гейтам (go-live: outbox-эскалация stop_close, отзыв токена, hardening,
  аудит отказов; Ф4: redelivery паузы; до Ф2: OPS13-reconcile сирот).
- **Оператору:** реальные ключи Bybit + ЖИВАЯ торговля = ОТДЕЛЬНЫЙ гейт go-live (не сейчас; Ф2 деплой — в
  безопасном режиме без реальных ключей). `orchestrator/.env` содержит RAILWAY_API_TOKEN Оператора (gitignored).

## 6. Следующий шаг (конкретно)
**Адаптер картриджа Пифагора (Ф2)** на ветке `task/f2-pifagor-cartridge`:
1. Recon-2: как достать телеметрию БЕЗ dashboard (viewmodel не вендорен) — equity/curve из `CapitalStore`/
   `Ledger`, сделки из realised-журнала (`state`/`storage`), health из `killswitch`/capital. Точки управления
   pause/stop_close → `risk_capital.killswitch` (+ config).
2. Тонкий read-only адаптер по Контракту Бота v0 (эталон = `bots/paper-bot`): heartbeat ≤60с +
   equity/trades/events + команды→killswitch. **4xx-классификация транзиентное/перманентное + backoff —
   ОБЯЗАТЕЛЬНА (Куратор #7).** Тесты маппинга (мок стора).
3. Образ (Dockerfile вокруг vendor/ + адаптер) → деплой Railway тем же конвейером что paper-bot, в
   БЕЗОПАСНОМ режиме (без реальных ключей/торговли) → сквозняк телеметрии+команд → доложить Куратору.
План — `wiki/progress/f2-pifagor-cartridge.md`.

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -1 main` = `7af4d09`; ветка `task/f2-pifagor-cartridge` = `07b4513`; обе в origin.
- [ ] Прочитать `_curator/DIRECTIVES.md` (разборы #5–#9) + `_curator/PROTOCOL.md` — автономный режим, гейт Ф2, план Пифагора.
- [ ] CI на main зелёный (GitHub Actions: core + orchestrator + paper-bot).
- [ ] `bots/pifagor/vendor/` существует (66 файлов, живой субсет), `bots/pifagor/README.md` пинует `b75bd17`. Оригинал `~/Desktop/pifagor-v81` НЕ трогать (только чтение).
- [ ] Docker + dev DB: `docker compose -f infra/docker-compose.dev.yml up -d --wait`. macOS: если импорт бинарников висит — `xattr -dr com.apple.quarantine <venv>` (orchestrator/.venv уже снят).
- [ ] Тесты: core `cd core && DATABASE_URL=… .venv/bin/pytest -q` → 81; orchestrator → 23; paper-bot → 22.
- [ ] `orchestrator/.env` (gitignored) содержит RAILWAY_API_TOKEN Оператора — НЕ коммитить, НЕ печатать в лог (закон №2).
- [ ] QUEUE: вендор-отклонение (engine/app/state) ждёт разбора Куратора.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 4 → Session 5.
