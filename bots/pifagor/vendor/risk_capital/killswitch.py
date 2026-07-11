# -*- coding: utf-8 -*-
"""risk_capital.killswitch — портфельный рубильник по live-equity (Веха 4 фича 1, ADR 0010).

check() — ЧИСТАЯ: по просадке от пика (peak−equity)/peak отдаёт NORMAL / ALARM (−40%) / STOP (−50%).
Меряется по LIVE-equity биржи (mark-to-market), НЕ по working-леджеру (docs/02 §5, ADR 0010 реш.1).
peak — исторический максимум (HWM, реш.2). STOP ЗАЩЁЛКИВАЕТСЯ (killswitch_active в capital_state) —
авто-возобновления нет, только clear_killswitch() (кнопка дашборда — фича 3). ALARM вычисляемая
(alarm_active отражает текущий снимок). safe_equity() — fail-closed на {'err'} брокера.

Проводку в 15m-цикл (evaluate на каждом снимке + гейт is_halted до постановки ноги) делает Веха 5;
здесь — чистая логика + персист защёлки, БЕЗ вызова брокера/цикла. Пороги инъектятся (config.risk).
"""

NORMAL = "NORMAL"
ALARM = "ALARM"
STOP = "STOP"


def drawdown(total_equity, peak):
    """Просадка от пика, доля [0..1]. peak<=0 -> 1.0 (нет валидного базиса -> макс. просадка,
    fail-safe в сторону STOP)."""
    if peak <= 0:
        return 1.0
    return max(0.0, (peak - total_equity) / peak)


def check(total_equity, peak, *, killswitch_dd, alarm_dd):
    """ЧИСТАЯ. DD=(peak−equity)/peak: DD>=killswitch_dd -> STOP; DD>=alarm_dd -> ALARM; иначе NORMAL.
    Пороги инъектятся (config.risk.KILLSWITCH_DD=0.50 / ALARM_DD=0.40, инвариант 0<alarm<kill<1)."""
    dd = drawdown(total_equity, peak)
    if dd >= killswitch_dd:
        return STOP
    if dd >= alarm_dd:
        return ALARM
    return NORMAL


def update_peak(total_equity, peak):
    """HWM: max(peak, equity) — пик растёт только вверх, не сбрасывается (реш.2)."""
    return max(peak, total_equity)


def safe_equity(broker_result):
    """total_equity из broker.get_equity_usdt() как float, иначе None при {'err'} / отсутствии / None
    (fail-closed: None -> вызывающий слой (Веха 5) не ставит новые ноги)."""
    if not isinstance(broker_result, dict) or "err" in broker_result:
        return None
    tot = broker_result.get("total_equity")
    return float(tot) if tot is not None else None


def _persist_state(row, state):
    """В строке леджера: alarm_active = state in {ALARM,STOP}; STOP ЗАЩЁЛКИВАЕТ killswitch_active=1
    (не снимается на NORMAL — только clear_killswitch). Защёлка sticky, тревога — вычисляемая."""
    row["alarm_active"] = 1 if state in (ALARM, STOP) else 0
    if state == STOP:
        row["killswitch_active"] = 1


def apply_state(store, state):
    """Персистить состояние рубильника в capital_state (set-часть защёлки; запись безусловная —
    идемпотентна). Возвращает state (или None, если леджер не засеян — mutate вернул False).
    В 15m-цикле (Веха 5) используется evaluate (peak+check+persist атомарно); apply_state — точечный set."""
    changed = store.mutate(lambda row: (_persist_state(row, state), True)[1])
    return state if changed else None


def clear_killswitch(store):
    """Ручной сброс защёлки (кнопка дашборда — фича 3 / Веха 5): killswitch_active=0. True, если
    строка есть."""
    return store.mutate(lambda row: (row.__setitem__("killswitch_active", 0), True)[1])


def is_halted(store):
    """True, если рубильник защёлкнут (killswitch_active=1) -> вызывающий не ставит новые ноги и
    отменяет незалитые (Веха 5). Не засеян -> False."""
    row = store.get()
    return bool(row and row.get("killswitch_active"))


def evaluate(store, total_equity, *, killswitch_dd, alarm_dd, debounce_ticks=2):
    """ЕДИНАЯ атомарная точка на снимок счёта (один mutate, как apply_pnl/refinance — без гонок):
    обновить peak (HWM) -> вычислить state -> alarm_active + защёлка STOP. Возвращает state
    (NORMAL/ALARM/STOP) или None, если total_equity недоступен (fail-closed) или леджер не засеян.

    ДЕБАУНС ложного STOP (5.7 п.4): защёлку `killswitch_active` ставим ТОЛЬКО при STOP-уровне
    `debounce_ticks` тиков (счётчик `stop_streak`). Серия ПЕРСИСТИТ через рестарт (сброса на старте
    больше НЕТ — хвост «дебаунс vs краш-луп»): краш-луп при реальной −50% накапливает серию через
    рестарты + ранний замер в `app/main` → защёлкивается. Два режима плохого чтения РАЗНЫЕ: (a) None/{err}
    (таймаут/пустой totalEquity) → ранний return, серию НЕ трогает (fail-closed); (b) заниженное-но-ВАЛИДНОЕ
    totalEquity STOP-уровня (частично-инициализированный UNIFIED после реконнекта — редкое) → дебаунс от
    ОДИНОЧНОГО такого чтения защищает (нужно 2). peak(HWM)/alarm_active — СРАЗУ. Реальная просадка ≥2 тика → защёлка.
    else-ветка гасит серию при ЛЮБОМ не-STOP замере → унаследованная серия=1 тухнет на 1-м здоровом тике."""
    if total_equity is None:                       # снимок недоступен (safe_equity вернул None) -> не меняем состояние, не торгуем
        return None
    box = {}

    def _eval(row):
        peak = update_peak(total_equity, row["peak_equity"])
        row["peak_equity"] = peak
        state = check(total_equity, peak, killswitch_dd=killswitch_dd, alarm_dd=alarm_dd)
        row["alarm_active"] = 1 if state in (ALARM, STOP) else 0    # тревога — вычисляемая, сразу
        if state == STOP:
            streak = int(row.get("stop_streak") or 0) + 1
            row["stop_streak"] = streak
            if streak >= debounce_ticks:                           # STOP N тиков подряд → защёлка (sticky)
                row["killswitch_active"] = 1
        else:
            row["stop_streak"] = 0                                  # не STOP → серия сброшена
        box["state"] = state
        return True

    changed = store.mutate(_eval)
    return box.get("state") if changed else None


def reset_stop_streak(store):
    """Ручной/восстановительный сброс дебаунс-счётчика STOP. НА СТАРТЕ БОЛЬШЕ НЕ ЗОВЁТСЯ (хвост «дебаунс vs
    краш-луп»: серия персистит через рестарт, иначе краш-луп при реальной −50% никогда не защёлкивался).
    Оставлена как утилита (напр. ручной сброс). Леджер не засеян → no-op (False).
    ВНИМАНИЕ: НЕ звать из `clear_killswitch` — при длящейся реальной просадке серия≥2 даёт мгновенную
    ре-защёлку (намеренная страховка re-STOP, ADR 0010); обнуление серии растянуло бы её на 2 тика."""
    return store.mutate(lambda row: (row.__setitem__("stop_streak", 0), True)[1])
