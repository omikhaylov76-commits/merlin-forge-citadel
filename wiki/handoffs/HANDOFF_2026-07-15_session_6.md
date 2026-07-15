# HANDOFF: Session 6 → Session 7

**From:** Session 6 (Инженер, Claude Code) · **Date:** 2026-07-15
**Веха:** **Ф3 (CRM + биллинг HWM) — денежный блок ПОСТРОЕН и отревьюен.** Осталось Telegram-алерты (отложено Оператором).

---

## 1. Состояние
Полный денежный путь Ф3 в main и работает: **клиент → договор → активация счёта (baseline) →
месячные периоды (генератор) → расчёт комиссии HWM**. Каждая деньги-фича прошла **независимое
адверсариальное ревью ×2** (find + verify), поймала и закрыла критические money-баги до main.
- **main @ `15abecb`** (pushed, в синке, дерево чистое). CI на main зелёный.
- Миграции: 0001–0008 (0005 CRM, 0006 billing, 0007 ≤1-signed, 0008 billing-lifecycle).
- Тесты ядра: ~156 функций (core), все зелёные в CI (Postgres). **БД-тесты локально не гоняются**
  (Docker не поднимаем, #12) — проверка через CI (джоба `core` с Postgres-сервисом).
- Облако (Railway `merlin-forge-citadel`): ядро+Postgres+картридж живы с Ф2 (публичный
  `core-production-429b.up.railway.app`). НО миграции 0005–0008 на облачное ядро **ещё не катились**
  (деплой ядра не триггерил в этой сессии — только код+CI).

## 2. Сделано в сессии (всё в main, --no-ff, каждое отдельной веткой кроме мелочей)
- **#20** дыра `/docs` на публичном ядре закрыта (create_app docs off) + передеплой + curl-простук.
- **«Малыш Мерлин» (#11):** архив Пифагора @b75bd17 в 3 местах (тег+release pifagor-v81, release-ассет
  Цитадели, локальный клон) + залоченный профиль-эталон `reference/malysh-merlin-profile-v8.3.json` +
  **ADR-0014**. SHA256 сверен.
- **MFC-F3-1 CRM-схема (0005):** clients + exchange_accounts + активация отложенных FK instances (ADR-0013).
- **Биллинг HWM (0006) + ADR-0011 финализирована (#27):** contracts/billing_periods/cashflows + движок
  `app/billing.py` (compute_period + close_period, снапшот fee_pct, immutable-период, EXCLUDE-overlap).
- **MFC-F3-2 CRM-API (0007):** операторский CRUD clients/exchange_accounts/contracts + RBAC + аудит +
  v1-гейт договора (единый `billing.v1_unsupported_reason` для API и движка) + ≤1 signed/клиент.
- **MFC-F3-3 генератор периодов (0008):** `app/periods.py` (activate_billing baseline MON3 / generate_due_periods
  свёртка часового / terminate_billing) + операторский API `routes_billing.py` + свёртка `billing-period-generator`.

## 3. Решения/находки сессии (ADR/DIRECTIVES/QUEUE)
- **ADR-0011** финализирована (accepted, #27): формула HWM (профит-пространство, перенос убытка,
  депозит/вывод-абсолют, снапшот fee_pct, месяц v1, equity из авторитетного источника MON3).
- **ADR-0014** «Малыш Мерлин».
- Директивы Куратора #20–#31 (пауза-политика биллинга #29/#30, GO генератора #31, fee_pct=0 законен).
- **Ревью поймало 🔴 (все закрыты):** движок — порядок закрытия периодов; CRM-API — billing_period=quarter
  в обход v1-гейта; генератор — двойной счёт до-активационных депозитов (окно net_deposits зажато до
  billing_activated_at).

## 4. На разборе у Куратора (QUEUE, ГОТОВО К РАЗБОРУ) + остаточные 🟢
Куратор ещё НЕ разбирал: биллинг-движок, CRM-API, генератор периодов. Остаточные (не блокеры, в QUEUE):
- audit-событие/readout на «тихий пропуск» генератора (нет договора/смена валюты) — сейчас log-only;
- пропорция комиссии при терминации середины месяца (сейчас полный месяц, соответствует ADR — подтвердить);
- `instance_id` в billing_periods не заполняется (per-instance роллап #23-доп — Ф4?);
- смена валюты договора между периодами → счёт pending (модель v1 — ок?);
- ниты NEW-3 (гонка create-signed → 400 не 409), NEW-4 (no-op PATCH без аудита) — приняты как есть.

## 5. Секреты (НИКОГДА в git/лог/чат — закон №2)
- `orchestrator/.env` (gitignored): RAILWAY_API_TOKEN + RAILWAY_PROJECT_ID.
- `_curator/secrets.env` (gitignored): demo-ключи Bybit.
- Облачные env Railway (не в git): DATABASE_URL, BOOTSTRAP_* у ядра; MF_*/BYBIT_* у картриджа.
- Telegram-алертам (когда возьмём): токен бота @BotFather + chat_id Оператора — кладёт Оператор, не Инженер.

## 6. Следующий шаг (конкретно)
Роадмап Ф3: осталась одна фича — **Telegram-алерты** (`[→]` ОТЛОЖЕНО Оператором 2026-07-15, «не к спеху»).
Возобновить, когда Оператор даст токен бота + chat_id. До тех пор:
- **Ждём разбор Куратора** по денежному блоку (движок/CRM-API/генератор) — возможны правки по его находкам.
- Опционально (не блокер): катнуть миграции 0005–0008 на ОБЛАЧНОЕ ядро (передеплой mfc-core) — сейчас
  облако на схеме 0004. Требует гейта Оператора на продовый передеплой (как #20).
- Icebox/go-live-хвосты (request-id серверно, is_active клиента через API, reference-hardening) — по нужде.

## 7. Проверка для нового чата
- [ ] `git -C ~/Desktop/merlin-forge-citadel log --oneline -1 main` = `15abecb`; в синке; дерево чистое.
- [ ] Прочитать `_curator/DIRECTIVES.md` (#20–#31) + `_curator/PROTOCOL.md`; QUEUE — 3 «ГОТОВО К РАЗБОРУ».
- [ ] CI на main зелёный (core+orchestrator+paper-bot+pifagor-cartridge+cartridge-image+core-image).
- [ ] Есть ли НОВАЯ директива Куратора (#32+) с разбором денежного блока — если да, начать с его правок.
- [ ] Схема: `alembic heads` = `0008_billing_lifecycle`; облачное ядро на 0004 (миграции 0005–0008 не катились).
- [ ] Telegram-алерты — отложены; брать только с токеном бота+chat_id от Оператора.
- [ ] Секреты gitignored, не печатать.

---
**Секретов в хэндоффе нет.** Конец HANDOFF Session 6 → Session 7.
