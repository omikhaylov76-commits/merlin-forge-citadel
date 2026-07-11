# -*- coding: utf-8 -*-
"""risk_capital.providers — живые провайдеры для шва sizing (Веха 4 фича 1, ADR 0010).

Закрывают шов make_sizing_callback (sizing.py): на Вехе 3 working/risk приходили статичным config-сидом
(заглушки `lambda: 10000` / `lambda: risk_box['v']`), теперь — из ЖИВОГО леджера и состояния рубильника:

- working_provider — текущий working из ledger (база сайзинга, компаундится; guard: не засеян -> 0.0,
  working≤0 -> sizing даёт qty≈0 -> нога не ставится).
- risk_pct_provider — alarm-aware: RISK_PCT_PER_LEG в норме, RISK_PCT_ALARM при тревоге (alarm_active=1,
  выставляется killswitch.evaluate на −40%). При восстановлении (alarm_active=0) риск возвращается.

Модуль чист от config/IO (значения risk инъектятся). ПОДМЕНА провайдеров в make_sizing_callback БЕЗ
правок sizing/executor; саму проводку в Executor + 15m-цикл делает Веха 5.
"""


def make_working_provider(ledger):
    """zero-arg callable -> текущий working (float). Не засеян -> 0.0 (нога не ставится)."""
    def working_provider():
        snap = ledger.get()
        return snap["working"] if snap else 0.0
    return working_provider


def make_risk_pct_provider(ledger, *, risk_pct, risk_pct_alarm):
    """zero-arg callable -> risk% на ногу. alarm_active=1 (тревога −40%, killswitch.evaluate) -> risk_pct_alarm;
    иначе risk_pct. Читается НА ВЫЗОВЕ (крутилка/тревога живые). risk-значения инъектятся (config.risk
    в Вехе 5: RISK_PCT_PER_LEG / RISK_PCT_ALARM)."""
    def risk_pct_provider():
        row = ledger.store.get()
        if row and row.get("alarm_active"):
            return risk_pct_alarm
        return risk_pct
    return risk_pct_provider
