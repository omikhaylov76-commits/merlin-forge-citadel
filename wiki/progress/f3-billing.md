---
type: progress
title: Ф3 биллинг — данные (contracts/billing_periods/cashflows) + движок HWM
tags: [f3, billing, hwm, money, adr-0011]
updated: 2026-07-14
sources: [wiki/decisions/0011-billing-hwm-model.md, _curator/DIRECTIVES.md#23, _curator/DIRECTIVES.md#27]
---
# progress: Ф3 биллинг (по #27, ADR-0011 финализирована)

Порядок Куратора (#23): ДАННЫЕ → ДВИЖОК HWM + эталонные тесты → алерты. Биллинг = деньги →
**независимое адверсариальное ревью ПЕРЕД merge обязательно**. Без UI/портала (Ф4), без реальных
денег/ключей (go-live). Проверка — на демо/выдуманных клиентах (юнит-тесты + сценарий).

Последний коммит: 532399c (+ вики 295b48f)

## MFC-F3-2 — ДАННЫЕ (миграция 0006 + модели + schema-тесты)
Типизированные колонки (ядро владеет биллингом, НЕ jsonb; #23). Все per-client — переменные, дефолты в ().
- [ ] 1. `contracts`(client_id FK; payment_model[profit_hwm(деф)/capital_fixed/hybrid/subscription];
      fee_pct(0.15, CHECK 0..1); high_water_mark(true); mgmt_fee_pct(0); hurdle_pct(0);
      billing_period[month(деф)/quarter] — #26 колонку хранить, quarter-логику НЕ делать; capital(1000, CHECK≥500);
      withdrawal_notice_days(3); currency[USDT(деф)/USDC]; status[draft(деф)/signed/suspended])
- [ ] 2. `billing_periods`(account_id FK, client_id FK, contract_id FK, instance_id UUID-nullable — per-instance
      роллап #23-доп; period_start/end UTC; start_equity/end_equity; net_deposits; period_net_trading; cum_profit;
      hwm; fee_pct-СНАПШОТ; commission; currency; status[open/closed]; adjustments_json; created_at/closed_at)
      + триггер immutability на status='closed' (как audit_log append-only)
- [ ] 3. `cashflows`(account_id FK, kind[deposit/withdrawal]+CHECK, amount>0, ts, actor) — #24 MON1
- [ ] 4. Модели + schema-тесты (CHECK fee/capital/enum; FK; immutability закрытого периода). CI (Postgres).

## MFC-F3-3 — ДВИЖОК HWM (billing.py + эталонные тесты + адверс-ревью)
- [ ] 5. `billing.py`: compute периода по канонической формуле ADR-0011 (period_net_trading = Δequity − net_deposits;
      cum_profit += ...; commission = fee_pct × max(0, cum_profit − hwm_prev − hurdle); hwm = max(hwm_prev, cum_profit)).
      Потоки-абсолют (исключены из trading). mgmt/hurdle заложены =0 в v1.
- [ ] 6. `close_period(account, period)`: снапшот fee_pct из активного договора → запись closed-леджера
      (immutable) + событие аудита («commission_calculated»). Каденция v1 = месяц (UTC).
- [ ] 7. ЭТАЛОННЫЕ тесты (закон №8, #27): −3000→0, +8000→fee×5000; 10000→с10000, +3000→с3000;
      депозит(планка вверх/не прибыль); вывод-абсолют(планка вниз/не убыток); перенос убытка; hurdle0/mgmt0;
      снапшот fee_pct (смена тарифа не задним числом). Demo-equity засеяны в тестах (источник equity — MON3).
- [ ] 8. Внутренний путь/CLI прогона сценария на демо-клиенте (доказать движок вживую, не только юниты).
- [ ] 9. **Независимое адверсариальное ревью (агент) — ОБЯЗАТЕЛЬНО (деньги)** → фиксы → ⛔ merge.
- [ ] 10. roadmap/log/QUEUE; ADR-0011 уже финализирована.

## Границы
UI/дашборд/портал/консоль — НЕ трогаем (Ф4). Реальные ключи/биржа/деньги — СТОП (go-live). Профили/крутилки — Ф5.
exchange_accounts.key_ciphertext — только шифр (ADR-0004), в v1 демо; ввод ключа = операторский путь (#25), UI позже.
Каденция quarter, payment_model≠profit_hwm, mgmt/hurdle≠0 — колонки есть, логика позже (не сейчас).
