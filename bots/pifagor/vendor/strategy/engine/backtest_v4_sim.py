#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v4 «тренд-продолжение» — машина состояний. Правила: docs/strategy_v4_rules.md.
Детект импульса на 4h, отработка ног на 15m, net-of-fees, in-sample/OOS.

Единый принцип: главный вопрос — «был ли уже взят профит в сетапе?»
  A. профита не было → защита: 1-2 ноги открыты → 0.236; все 3 без профита = ШОК → все на 0.5.
  B. профит был (лесенка) → самая глубокая открытая нога едет в расширение
     (0.5→1.618=B+0.618R, 0.618→1.272=B+0.272R); более мелкие открытые скальпят
     (0.382→0.236, 0.5→0.382). Цель динамическая (зальётся глубже — глубокая едет, мелкая в скальп).
Расширение: вышли за вершину → стоп в б/у; таймаут 12д → по рынку.
Новый хай до начала «езды» (профит был, открытых ног нет) → пересборка (конец сетапа, ре-детект).

Ноги независимы (лимитки висят). Чистка no_same_subbar_tp у всех. Издержки в pf._close.

УПРОЩЕНИЕ (помечено): пересборка реализована как «профит был + нет открытых ног + новый хай →
конец сетапа», и докетеч идёт через основной детектор на следующем 4h-баре (а не мгновенная
перестановка от нового экстремума). Пред-залив ратчет B — как в движке.
"""
import sys
import numpy as np
import pandas as pd

from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_v2_sim as v2
from . import backtest_15m_intrabar as ib

LV = [0.382, 0.5, 0.618]
NEXT_SCALP = {0.382: 0.236, 0.5: 0.382}     # скальп-цель более мелкой ноги
EXT_MAG = {0.5: 0.618, 0.618: 0.272}        # расширение: price = B + mag*R (fib -mag)


def _mk(lv, exit_px, outcome, exit_bar, entries, ebar, istop, side, cost, t4):
    """Богатая запись сделки для риск-модели: R считается через НАЧАЛЬНУЮ дистанцию стопа."""
    e = entries[lv]
    g = (exit_px - e) / e if side == "long" else (e - exit_px) / e
    d = abs(e - istop.get(lv, e)) / e * 100.0   # начальная дистанция стопа, % (для сайзинга)
    return {"fib": lv, "ret": (g - 2 * cost) * 100.0, "stopdist": d, "outcome": outcome,
            "t_in": int(t4[ebar[lv]]) if t4 is not None else int(ebar[lv]),
            "t_out": int(t4[exit_bar]) if t4 is not None else int(exit_bar)}


def run_v4(data, max_wait, *, no_same_subbar_tp=True, records=None, trend_ema=0,
           shock_events=None,
           no_retrace=pf.IMPULSE_NO_RETRACE, min_bar_pct=pf.MIN_BAR_PCT,
           stop_fib=pf.STOP_FIB, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT):
    o4, h4, l4, c4 = data["o4"], data["h4"], data["l4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    t4 = data.get("t4")
    n = len(c4); cost = (fee + slip) / 100.0
    # фильтр тренда (опц.): входим только по тренду EMA на момент НАЧАЛА импульса (i-1, без look-ahead)
    ema4 = pd.Series(c4).ewm(span=trend_ema, adjust=False).mean().to_numpy() if trend_ema > 0 else None
    trades = []
    i = 2
    while i < n:
        imp = pf.detect_impulse(o4, h4, l4, c4, i, no_retrace, None, 0.0, min_bar_pct)
        if imp is None:
            i += 1; continue
        side, A, B = imp
        if ema4 is not None and not np.isnan(ema4[i - 1]):
            up = c4[i - 1] > ema4[i - 1]
            if (side == "long" and not up) or (side == "short" and up):
                i += 1; continue
        lp = lambda L: pf.fib_price(A, B, L, side)
        entries = {lv: lp(lv) for lv in LV}; stop0 = lp(stop_fib)
        state = {lv: "pending" for lv in LV}; ebar = {}; istop = {}
        profit_taken = False; beyond_B = False; spring_recorded = False
        done = False; j = i + 1; wait = 0
        while j < n and not done:
            if all(state[lv] == "pending" for lv in LV):   # ратчет B до первого залива
                if (side == "long" and h4[j] > B) or (side == "short" and l4[j] < B):
                    B = h4[j] if side == "long" else l4[j]
                    entries = {lv: lp(lv) for lv in LV}; stop0 = lp(stop_fib); wait = 0; j += 1; continue
            s, e = offs[j], offs[j + 1]
            for hh, ll in zip(h15[s:e], l15[s:e]):
                filled_this = []
                for lv in LV:
                    if state[lv] == "pending":
                        px = entries[lv]
                        if ll <= px <= hh:
                            state[lv] = "open"; ebar[lv] = j; filled_this.append(lv); istop[lv] = stop0
                if (hh > B) if side == "long" else (ll < B):
                    beyond_B = True
                open_legs = [lv for lv in LV if state[lv] == "open"]
                if open_legs:
                    shock = (not profit_taken) and (len(open_legs) == 3)
                    deepest = max(open_legs)
                    done_legs = []
                    for lv in open_legs:
                        if not profit_taken:
                            T, estop = (lp(0.5) if shock else lp(0.236)), stop0
                        elif lv == deepest and lv in EXT_MAG:
                            T, estop = pf.fib_price(A, B, -EXT_MAG[lv], side), (entries[lv] if beyond_B else stop0)
                        elif lv == deepest:
                            T, estop = lp(0.236), stop0
                        else:
                            T, estop = lp(NEXT_SCALP[lv]), stop0
                        stop_hit = (ll <= estop) if side == "long" else (hh >= estop)
                        tgt_hit = (hh >= T) if side == "long" else (ll <= T)
                        if stop_hit:
                            pf._close(trades, side, ebar[lv], entries[lv], estop, estop, lv, j, "stop", cost); done_legs.append(lv)
                            if records is not None:
                                records.append(_mk(lv, estop, "stop", j, entries, ebar, istop, side, cost, t4))
                            # ШОК-стопаут: цену продавило через все 3 ноги в стоп → событие для модуля «пружина»
                            if shock and shock_events is not None and not spring_recorded:
                                shock_events.append({"A": A, "B": B, "side": side, "bar": j}); spring_recorded = True
                        elif tgt_hit and not (no_same_subbar_tp and lv in filled_this):
                            pf._close(trades, side, ebar[lv], entries[lv], estop, T, lv, j, "target", cost); done_legs.append(lv)
                            if records is not None:
                                records.append(_mk(lv, T, "target", j, entries, ebar, istop, side, cost, t4))
                            ret = (T - entries[lv]) if side == "long" else (entries[lv] - T)
                            if ret > 0:
                                profit_taken = True
                    for lv in done_legs:
                        state[lv] = "closed"
                # пересборка: профит был, открытых нет, новый хай → конец сетапа (ре-детект)
                if profit_taken and beyond_B and not any(state[lv] == "open" for lv in LV):
                    done = True; i = j + 1; break
                if all(state[lv] == "closed" for lv in LV):
                    done = True; i = j + 1; break
            if done:
                break
            wait += 1
            if wait >= max_wait:
                for lv in LV:
                    if state[lv] == "open":
                        pf._close(trades, side, ebar[lv], entries[lv], stop0, c4[j], lv, j, "timeout", cost)
                        if records is not None:
                            records.append(_mk(lv, c4[j], "timeout", j, entries, ebar, istop, side, cost, t4))
                done = True; i = j + 1; break
            j += 1
        if not done:
            i += 1
    return trades


def simulate_springs(data, events, max_wait=72, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT, no_same_subbar_tp=True):
    """Модуль «выкуп пружины» после ШОК-стопаута. На каждое событие (A,B,side,bar):
    2 лимитки на 1.618 и 2.0 (под низом импульса для long; зеркально для short),
    стоп за 2.2, общая цель 0.5 исходного импульса. Возвращает записи сделок (как _mk).
    Заканчиваем сетап: достигнута цель (отскок) → отмена остатка; либо все ноги закрыты; либо таймаут."""
    o4, c4 = data["o4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    t4 = data.get("t4"); n = len(c4); cost = (fee + slip) / 100.0
    SLV = [1.618, 2.0]
    recs = []
    for ev in events:
        A, B, side, bar = ev["A"], ev["B"], ev["side"], ev["bar"]
        lp = lambda L: pf.fib_price(A, B, L, side)
        entries = {L: lp(L) for L in SLV}
        sstop = lp(2.2); starget = lp(0.5)
        istop = {L: sstop for L in SLV}
        state = {L: "pending" for L in SLV}; ebar = {}
        j = bar; wait = 0; done = False   # старт со стоп-бара: пролив к 1.618 часто в том же движении
        while j < n and not done:
            s, e = offs[j], offs[j + 1]
            for hh, ll in zip(h15[s:e], l15[s:e]):
                filled_this = []
                for L in SLV:
                    if state[L] == "pending" and ll <= entries[L] <= hh:
                        state[L] = "open"; ebar[L] = j; filled_this.append(L)
                done_legs = []; target_hit = False
                for L in [x for x in SLV if state[x] == "open"]:
                    stop_hit = (ll <= sstop) if side == "long" else (hh >= sstop)
                    tgt_hit = (hh >= starget) if side == "long" else (ll <= starget)
                    if stop_hit:
                        recs.append(_mk(L, sstop, "stop", j, entries, ebar, istop, side, cost, t4)); done_legs.append(L)
                    elif tgt_hit and not (no_same_subbar_tp and L in filled_this):
                        recs.append(_mk(L, starget, "target", j, entries, ebar, istop, side, cost, t4)); done_legs.append(L); target_hit = True
                for L in done_legs:
                    state[L] = "closed"
                if target_hit or all(state[L] == "closed" for L in SLV):
                    done = True; break
            if done:
                break
            wait += 1
            if wait >= max_wait:
                for L in SLV:
                    if state[L] == "open":
                        recs.append(_mk(L, c4[j], "timeout", j, entries, ebar, istop, side, cost, t4))
                done = True; break
            j += 1
    return recs


# ── синтетические гейты ──────────────────────────────────────────────────────
def _ds(periods):
    o4 = []; h4 = []; l4 = []; c4 = []; h15 = []; l15 = []; offs = [0]
    for o, c, subs in periods:
        hs = [x[0] for x in subs]; ls = [x[1] for x in subs]
        o4.append(o); c4.append(c); h4.append(max(hs)); l4.append(min(ls))
        h15 += hs; l15 += ls; offs.append(len(h15))
    return {"o4": np.array(o4, float), "h4": np.array(h4, float), "l4": np.array(l4, float),
            "c4": np.array(c4, float), "h15": np.array(h15, float), "l15": np.array(l15, float),
            "offs": np.array(offs, np.int64)}


IMP = [(100, 100, [(100, 100)]), (100, 109, [(110, 100)]), (109, 119, [(120, 108)])]
# A=100,B=120,R=20 → 0.382=112.36 0.5=110 0.618=107.64 ; 0.236=115.28 ; 0.382scalp=112.36
# ext: 0.5→1.618=132.36 ; 0.618→1.272=125.44


def gates():
    ok = True
    # 1) ШОК: прямо вниз все три без профита → все на 0.5
    sh = run_v4(_ds(IMP + [(108, 110, [(113, 112), (113, 109), (109, 107), (111, 108)])]), 48, min_bar_pct=0.0)
    a = (any(t.entry_fib == 0.382 and t.outcome == "target" and t.ret_pct < 0 for t in sh)
         and any(t.entry_fib == 0.618 and t.outcome == "target" and t.ret_pct > 0 for t in sh))
    print(f"  шок: 0.382 в минус на 0.5, 0.618 в плюс на 0.5: {a}"); ok = ok and a
    # 2) ЛЕСЕНКА до 0.5 (одна): 0.382 берёт 0.236, 0.5 одна едет в 1.618
    ld5 = run_v4(_ds(IMP + [(108, 112, [(113, 112), (116, 113), (114, 109)]), (110, 132, [(133, 120)])]), 48, min_bar_pct=0.0)
    b = (any(t.entry_fib == 0.382 and t.outcome == "target" and t.ret_pct > 0 for t in ld5)
         and any(t.entry_fib == 0.5 and t.outcome == "target" and t.exit > 130 for t in ld5))
    print(f"  лесенка→0.5: 0.382 взяла 0.236, 0.5 уехала в 1.618 (>130): {b}"); ok = ok and b
    # 3) СЕРЕДИННЫЙ: 0.382 профит, заливаются 0.5 и 0.618 → 0.618 в 1.272, 0.5 скальп 0.382
    mid = run_v4(_ds(IMP + [(108, 112, [(113, 112), (116, 113), (114, 109), (110, 107)]),
                            (111, 126, [(126, 111)])]), 48, min_bar_pct=0.0)
    c = (any(t.entry_fib == 0.618 and t.outcome == "target" and t.exit > 120 for t in mid)        # 0.618 в расширение
         and any(t.entry_fib == 0.5 and t.outcome == "target" and 111 < t.exit < 120 for t in mid))  # 0.5 скальп 112.36
    print(f"  серединный: 0.618 в расширение(>120), 0.5 скальп на ~112.36: {c}"); ok = ok and c
    return ok


def slice_ds(d, p0, p1):
    s, e = int(d["offs"][p0]), int(d["offs"][p1])
    out = {"o4": d["o4"][p0:p1], "h4": d["h4"][p0:p1], "l4": d["l4"][p0:p1], "c4": d["c4"][p0:p1],
           "h15": d["h15"][s:e], "l15": d["l15"][s:e], "offs": d["offs"][p0:p1 + 1] - d["offs"][p0]}
    if "t4" in d:
        out["t4"] = d["t4"][p0:p1]
    return out


REFS = {
    "base":       dict(policy=v2.pol_base,       cancel_on_new_high=False, no_same_subbar_tp=True),
    "v1_live":    dict(policy=v2.pol_live,       cancel_on_new_high=False, no_same_subbar_tp=True),
    "v2_uniform": dict(policy=v2.pol_v2_uniform, cancel_on_new_high=True,  no_same_subbar_tp=True),
}
COINS = ["BTCUSDT", "ETHUSDT"]


def row(name, tr):
    m = pf.metrics(tr, name)
    if m.get("n", 0) == 0:
        return f"{name:<12}{'нет сделок':>12}"
    return (f"{name:<12}{m['n']:>7}{m['winrate_%']:>7}%{m['expectancy_%_per_trade']:>9}"
            f"{m['total_return_%']:>10}{str(m['profit_factor']):>7}{m['t_stat']:>7}")


def main():
    import os
    data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ds = {}
    for sym in COINS:
        p = os.path.join(data_dir, f"{sym}_15m_cex.csv")
        if os.path.exists(p):
            ds[sym] = ib.load_15m_as_4h(p)
    print("ГЕЙТЫ v4 (синтетика):")
    if not gates():
        print("✗ Гейты не прошли. Стоп."); sys.exit(1)
    print("✓ Гейты пройдены.\n")

    for mw in (72,):
        for split, lo, hi in [("IN-SAMPLE 0-60%", 0.0, 0.6), ("OUT-OF-SAMPLE 60-100%", 0.6, 1.0)]:
            print("=" * 66)
            print(f"{split} | MAX_WAIT={mw} | BTC+ETH 15m, net-of-fees")
            print("=" * 66)
            print(f"{'вариант':<12}{'сделок':>7}{'winrate':>8}{'эксп/сд':>9}{'итог%':>10}{'PF':>7}{'t':>7}")
            print("-" * 58)
            for nm, kw in REFS.items():
                tr = []
                for sym, d in ds.items():
                    p0 = max(int(len(d["c4"]) * lo), 2); p1 = int(len(d["c4"]) * hi)
                    tr += ib.run_intrabar(slice_ds(d, p0, p1), mw, **kw)
                print(row(nm, tr))
            tr = []
            for sym, d in ds.items():
                p0 = max(int(len(d["c4"]) * lo), 2); p1 = int(len(d["c4"]) * hi)
                tr += run_v4(slice_ds(d, p0, p1), mw)
            print(row("v4", tr))
            print()


if __name__ == "__main__":
    main()
