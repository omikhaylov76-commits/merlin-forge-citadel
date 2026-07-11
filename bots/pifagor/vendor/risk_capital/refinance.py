# -*- coding: utf-8 -*-
"""risk_capital.refinance — месячный рефинанс прибыли 50/50 working->cushion (Веха 4 фича 1, ADR 0010).

Граница периода — КАЛЕНДАРНЫЙ МЕСЯЦ UTC (месяц last_refinance_ts != месяцу now -> due). Прибыль
периода = (working+cushion) − last_refinance_total. profit>0 -> move=profit*split переносится
working->cushion (total НЕ меняется — внутренний перенос; структура само-делевереджится, доля cushion
растёт, docs/02 §4). Убыточный месяц -> дележа НЕТ (skip-on-loss), но baseline (last_refinance_ts/total)
сдвигается на текущий месяц/total, иначе тик зациклится «вечно due».

`split` инъектится (config.capital.REFINANCE_SPLIT, дефолт 0.5) — модуль чист от config/IO. Атомарно
через store.mutate (read-modify-write под локом). Отличие от наброска docs/06 `run_if_due(now, profit)`:
профит считается из стейта леджера, а не приходит аргументом (иначе границу месяца не определить) —
doc-sync docs/06 в под-шаге 5.
"""
from datetime import datetime, timezone

from .ledger import compute_ratio


def _month_of(iso_ts):
    """(год, месяц) из ISO-строки last_refinance_ts."""
    dt = datetime.fromisoformat(iso_ts)
    return (dt.year, dt.month)


def run_if_due(now, ledger, *, split):
    """now — datetime UTC; aware-время нормализуется к UTC, naive трактуется как UTC (ответственность
    вызывающего/scheduler). split клэмпится в [0,1] — защита инварианта working>=0 / ratio<=1 (основной
    гейт — config 0<REFINANCE_SPLIT<1). Возвращает (working', cushion') если рефинанс применён ИЛИ
    baseline установлен/сдвинут; None если не due (тот же месяц) или леджер не засеян. Атомарно через
    ledger.store.mutate (та же критическая секция, что apply_pnl — без гонок).

    Первый запуск после seed (last_refinance_ts is None): фиксируем ТОЛЬКО last_refinance_ts (месяц
    старта); baseline last_refinance_total НЕ трогаем (он задан seed) — прибыль первого частичного
    месяца поделится на ближайшей границе месяца, а не теряется."""
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    split = min(1.0, max(0.0, split))
    box = {}

    def _refi(row):
        cur_month = (now.year, now.month)
        last_ts = row.get("last_refinance_ts")
        if last_ts is None:                                   # после seed: фиксируем месяц старта, baseline (seed) НЕ трогаем
            row["last_refinance_ts"] = now.isoformat()
            box["result"] = (row["working"], row["cushion"])
            return True
        if _month_of(last_ts) == cur_month:                   # тот же месяц -> не due, ничего не меняем
            return False
        total = row["working"] + row["cushion"]
        profit = total - row["last_refinance_total"]
        if profit > 0:                                        # дележ только прибыльного месяца (skip-on-loss)
            move = profit * split
            row["working"] = row["working"] - move
            row["cushion"] = row["cushion"] + move
            row["ratio"] = compute_ratio(row["working"], row["cushion"])
        row["last_refinance_ts"] = now.isoformat()            # сдвиг baseline (и на loss — чтобы не зацикливаться)
        row["last_refinance_total"] = row["working"] + row["cushion"]
        box["result"] = (row["working"], row["cushion"])
        return True

    changed = ledger.store.mutate(_refi)
    return box.get("result") if changed else None
