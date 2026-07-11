#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PIFAGOR V7 — консолидированный движок: v4 + подтверждённые находки, ориентир BTC+ETH, + модуль «пружина».

База v4 (машина состояний шок/лесенка, EMA200, детект 4h / отработка 15m, net-of-fees) БЕЗ изменений, плюс:
  • Нога 2 (0.5) как самая глубокая в лесенке → БЕГУНОК до ext(leg2_ext) (V7: 2.0 = B+1.0R), стоп — БЕЗУБЫТОК
    за вершиной B (ступенчатый трейл отвергнут проверкой: режет правый хвост).
  • Нога 3 (0.618) как самая глубокая в лесенке → близкий выход 0.382 (V7), а не расширение 1.272.
  • Глубокий ШОК (все 3 ноги без профита) → всё на 0.5 (как v4) + СБОР shock-событий.
  • МОДУЛЬ «ПРУЖИНА / снятие ликвидности»: после шок-стопаута — 2 лимитки на 1.618/2.0 под низом импульса
    (зеркально для short), стоп 2.2, общая цель 0.5 исходного импульса (s4.simulate_springs).
    ВНИМАНИЕ: событие редкое → N мал → статистика пружины СЛАБАЯ (показываю вклад отдельно).

Ноги 0.382 и не-самые-глубокие — скальп как v4 (0.382→0.236, 0.5→0.382). Таймаут 72.

ГЕЙТ: run_v7(leg2_ext=0.618, leg3_mode="ext") == s4.run_v4 (без модуля пружины). BTC+ETH, стоп1.0, EMA200, RISK1%.
"""
import os, sys, numpy as np, pandas as pd
from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_v2_sim as v2
from . import backtest_15m_intrabar as ib
from . import backtest_v4_sim as s4
from . import risk_sim as rk
from .leg3_exit_test import submetrics, sysrow, portrow

from ._paths import DATA_DIR as DD
NEXT_SCALP = s4.NEXT_SCALP

# ── V7 defaults (лучшие находки) ──
V7 = dict(leg2_ext=1.0, leg3_mode="0.382")     # нога2→2.0, нога3→0.382, БУ-стоп


def run_v7(data, max_wait, *, leg2_ext=1.0, leg3_mode="0.382",
           shock_events=None, records=None, setup_log=None, trend_ema=0, detect_fn=None,
           no_same_subbar_tp=True, no_retrace=pf.IMPULSE_NO_RETRACE, min_bar_pct=pf.MIN_BAR_PCT,
           stop_fib=pf.STOP_FIB, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT):
    legs = [0.382, 0.5, 0.618]
    o4, h4, l4, c4 = data["o4"], data["h4"], data["l4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    t4 = data.get("t4"); n = len(c4); cost = (fee + slip) / 100.0
    ema4 = pd.Series(c4).ewm(span=trend_ema, adjust=False).mean().to_numpy() if trend_ema > 0 else None
    trades = []; i = 2
    while i < n:
        imp = (detect_fn(o4, h4, l4, c4, i) if detect_fn is not None
               else pf.detect_impulse(o4, h4, l4, c4, i, no_retrace, None, 0.0, min_bar_pct))
        if imp is None:
            i += 1; continue
        side, A, B = imp
        if ema4 is not None and not np.isnan(ema4[i - 1]):
            up = c4[i - 1] > ema4[i - 1]
            if (side == "long" and not up) or (side == "short" and up):
                i += 1; continue
        lp = lambda L: pf.fib_price(A, B, L, side)
        ext = lambda mag: pf.fib_price(A, B, -mag, side)
        entries = {lv: lp(lv) for lv in legs}; stop0 = lp(stop_fib)
        state = {lv: "pending" for lv in legs}; ebar = {}; istop = {}
        profit_taken = False; beyond_B = False; spring_recorded = False
        done = False; j = i + 1; wait = 0
        while j < n and not done:
            if all(state[lv] == "pending" for lv in legs):
                if (side == "long" and h4[j] > B) or (side == "short" and l4[j] < B):
                    B = h4[j] if side == "long" else l4[j]
                    entries = {lv: lp(lv) for lv in legs}; stop0 = lp(stop_fib); wait = 0; j += 1; continue
            s, e = offs[j], offs[j + 1]
            for hh, ll in zip(h15[s:e], l15[s:e]):
                filled_this = []
                for lv in legs:
                    if state[lv] == "pending" and ll <= entries[lv] <= hh:
                        state[lv] = "open"; ebar[lv] = j; filled_this.append(lv); istop[lv] = stop0
                if (hh > B) if side == "long" else (ll < B):
                    beyond_B = True
                open_legs = [lv for lv in legs if state[lv] == "open"]
                if open_legs:
                    shock = (not profit_taken) and (len(open_legs) == 3)
                    deepest = max(open_legs); done_legs = []
                    for lv in open_legs:
                        ride = False
                        if not profit_taken:
                            T, estop = (lp(0.5) if shock else lp(0.236)), stop0
                        elif lv == deepest and lv == 0.618:
                            if leg3_mode == "ext":
                                ride = True; T = ext(0.272)
                            else:
                                T, estop = lp(float(leg3_mode)), stop0
                        elif lv == deepest and lv == 0.5:
                            if leg2_ext <= 0.0:
                                T, estop = lp(0.0), stop0
                            else:
                                ride = True; T = ext(leg2_ext)
                        elif lv == deepest:
                            T, estop = lp(0.236), stop0
                        else:
                            T, estop = lp(NEXT_SCALP[lv]), stop0
                        if ride:
                            estop = entries[lv] if beyond_B else stop0
                        stop_hit = (ll <= estop) if side == "long" else (hh >= estop)
                        tgt_hit = (hh >= T) if side == "long" else (ll <= T)
                        if stop_hit:
                            pf._close(trades, side, ebar[lv], entries[lv], estop, estop, lv, j, "stop", cost); done_legs.append(lv)
                            if records is not None:
                                records.append(s4._mk(lv, estop, "stop", j, entries, ebar, istop, side, cost, t4))
                            if shock and shock_events is not None and not spring_recorded:
                                shock_events.append({"A": A, "B": B, "side": side, "bar": j}); spring_recorded = True
                        elif tgt_hit and not (no_same_subbar_tp and lv in filled_this):
                            pf._close(trades, side, ebar[lv], entries[lv], estop, T, lv, j, "target", cost); done_legs.append(lv)
                            if records is not None:
                                records.append(s4._mk(lv, T, "target", j, entries, ebar, istop, side, cost, t4))
                            if ((T - entries[lv]) if side == "long" else (entries[lv] - T)) > 0:
                                profit_taken = True
                    for lv in done_legs:
                        state[lv] = "closed"
                if profit_taken and beyond_B and not any(state[lv] == "open" for lv in legs):
                    done = True; i = j + 1; break
                if all(state[lv] == "closed" for lv in legs):
                    done = True; i = j + 1; break
            if done:
                break
            wait += 1
            if wait >= max_wait:
                for lv in legs:
                    if state[lv] == "open":
                        pf._close(trades, side, ebar[lv], entries[lv], stop0, c4[j], lv, j, "timeout", cost)
                        if records is not None:
                            records.append(s4._mk(lv, c4[j], "timeout", j, entries, ebar, istop, side, cost, t4))
                done = True; i = j + 1; break
            j += 1
        if setup_log is not None:
            filled = tuple(sorted(lv for lv in legs if state[lv] != "pending"))
            if filled:
                setup_log.append(filled)
        if not done:
            i += 1
    return trades


def run_v7_full(d, mw=72, *, with_spring=True, records=None, **kw):
    """V7 = ядро + (опц.) модуль пружины. Возвращает (trades, records)."""
    rc = records if records is not None else []
    ev = []
    tr = run_v7(d, mw, records=rc, shock_events=ev, **kw)
    spring_n = 0
    if with_spring:
        sp = s4.simulate_springs(d, ev)
        rc += sp; spring_n = len(sp)
    return tr, rc, len(ev), spring_n


SETS = {"BTC+ETH": ["BTCUSDT", "ETHUSDT"], "4 крупные": ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "VETUSDT"]}
ALL = sorted({c for v in SETS.values() for c in v})
_CACHE = {}
def _ds(s):
    if s not in _CACHE:
        _CACHE[s] = ib.load_15m_as_4h(os.path.join(DD, f"{s}_15m_cex.csv"))
    return _CACHE[s]


def main():
    # ── ГЕЙТ ──
    print("ГЕЙТ: run_v7(leg2=0.618, leg3=ext) == s4.run_v4 (BTC+ETH, EMA200, stop1.0, mbp 2.0/2.5):")
    ok = True
    for mbp in (2.0, 2.5):
        for sym in ["BTCUSDT", "ETHUSDT"]:
            a = [v2._tk(t) for t in s4.run_v4(_ds(sym), 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp)]
            b = [v2._tk(t) for t in run_v7(_ds(sym), 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp,
                                           leg2_ext=0.618, leg3_mode="ext")]
            if a != b:
                print(f"  ✗ {sym} {mbp}: {len(a)} vs {len(b)}"); ok = False
    if not ok:
        sys.exit("гейт не прошёл")
    print("✓ Гейт пройден: V7-ядро в v4-режиме == run_v4.\n")

    for label, coins in SETS.items():
        ncoin = len(coins)
        for mbp in (2.0, 2.5):
            print("=" * 92)
            print(f"V7  |  {label}  |  mbp={mbp}  |  стоп1.0 EMA200 RISK1%  (нога2→2.0 БУ, нога3→0.382)")
            print("=" * 92)
            for split, lo, hi in [("FULL", 0.0, 1.0), ("OOS 60-100%", 0.6, 1.0)]:
                # v4 baseline для сравнения
                tr0, rc0 = [], []
                # V7 ядро (без пружины) и V7+пружина
                rc_core = []; rc_spr = []; ev_tot = 0; spr_tot = 0
                tr_v4 = []
                for sym in coins:
                    d = _ds(sym); p0 = max(int(len(d["c4"]) * lo), 2); p1 = int(len(d["c4"]) * hi)
                    sl = s4.slice_ds(d, p0, p1)
                    tr_v4 += s4.run_v4(sl, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp, records=rc0)
                    # ядро
                    run_v7(sl, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp, records=rc_core, **V7)
                    # пружина: события из отдельного прогона ядра
                    ev = []
                    run_v7(sl, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp, shock_events=ev, **V7)
                    sp = s4.simulate_springs(sl, ev)
                    ev_tot += len(ev); spr_tot += len(sp); rc_spr += sp
                rc_v7s = rc_core + rc_spr
                print(f"  [{split}]")
                print(f"    v4 базовый      : порт {portrow(rc0, ncoin)}")
                print(f"    V7 ядро         : порт {portrow(rc_core, ncoin)}")
                print(f"    V7 + пружина    : порт {portrow(rc_v7s, ncoin)}   (шок-событий {ev_tot}, пружин-сделок {spr_tot})")
                if rc_spr:
                    print(f"    пружина отдельно: {submetrics(rc_spr, 1.618)} (1.618) / {submetrics(rc_spr, 2.0)} (2.0)")
            print()


if __name__ == "__main__":
    main()
