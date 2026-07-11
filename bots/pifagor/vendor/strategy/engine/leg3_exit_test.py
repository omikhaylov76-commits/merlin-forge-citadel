#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Идея пользователя: НЕ выбрасывать 3-ю ногу (0.618), а в режиме «лесенки»
(profit_taken=True) давать её — когда она самая глубокая открытая — БЛИЗКИЙ выход
0.5 / 0.382 / 0.236 вместо текущей езды в расширение 1.272 (EXT_MAG[0.618]).

Гипотеза: глубокая нога умирает не из-за входа, а из-за далёкой цели; с реалистичным
близким выходом 3-я нога может стать прибыльной и снова иметь смысл.

МЕТОД: run_v4x — побитовая копия run_v4 с двумя ручками:
  leg3_mode ∈ {"ext"(текущая),"0.5","0.382","0.236"} — выход 0.618-ноги в лесенке (только когда она deepest).
  drop_leg3 — вообще не заходить в 0.618 (схема 2 ноги).
ГЕЙТ ВЕРНОСТИ: run_v4x(leg3_mode="ext", drop_leg3=False) ОБЯЗАН посделочно совпасть с
проверенным s4.run_v4 на BTC+ETH (иначе копия неверна → стоп).

Сравниваем: 2 ноги (наша текущая рекомендация) vs 3 ноги с разными выходами 0.618.
Метрики: система (n/wr/exp/PF), только-0.618 (вклад глубокой ноги), портфель (DD/Calmar/итог, RISK 1%).
BTC+ETH, сигнал 4h / отработка 15m, стоп 1.0, EMA200. FULL + IN-SAMPLE + OUT-OF-SAMPLE.
"""
import os, sys, numpy as np, pandas as pd
from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_v2_sim as v2
from . import backtest_15m_intrabar as ib
from . import backtest_v4_sim as s4
from . import risk_sim as rk

from ._paths import DATA_DIR as DD
COINS = ["BTCUSDT", "ETHUSDT"]
NEXT_SCALP = s4.NEXT_SCALP
EXT_MAG = s4.EXT_MAG


def run_v4x(data, max_wait, *, leg3_mode="ext", drop_leg3=False,
            no_same_subbar_tp=True, records=None, trend_ema=0,
            no_retrace=pf.IMPULSE_NO_RETRACE, min_bar_pct=pf.MIN_BAR_PCT,
            stop_fib=pf.STOP_FIB, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT):
    """Копия s4.run_v4 + ручки leg3_mode / drop_leg3. Всё прочее идентично."""
    legs = [0.382, 0.5] if drop_leg3 else [0.382, 0.5, 0.618]
    o4, h4, l4, c4 = data["o4"], data["h4"], data["l4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    t4 = data.get("t4")
    n = len(c4); cost = (fee + slip) / 100.0
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
        entries = {lv: lp(lv) for lv in legs}; stop0 = lp(stop_fib)
        state = {lv: "pending" for lv in legs}; ebar = {}; istop = {}
        profit_taken = False; beyond_B = False
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
                    if state[lv] == "pending":
                        px = entries[lv]
                        if ll <= px <= hh:
                            state[lv] = "open"; ebar[lv] = j; filled_this.append(lv); istop[lv] = stop0
                if (hh > B) if side == "long" else (ll < B):
                    beyond_B = True
                open_legs = [lv for lv in legs if state[lv] == "open"]
                if open_legs:
                    shock = (not profit_taken) and (len(open_legs) == 3)
                    deepest = max(open_legs)
                    done_legs = []
                    for lv in open_legs:
                        if not profit_taken:
                            T, estop = (lp(0.5) if shock else lp(0.236)), stop0
                        elif lv == deepest and lv in EXT_MAG:
                            if lv == 0.618 and leg3_mode != "ext":
                                T, estop = lp(float(leg3_mode)), stop0          # << близкий выход 3-й ноги
                            else:
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
                                records.append(s4._mk(lv, estop, "stop", j, entries, ebar, istop, side, cost, t4))
                        elif tgt_hit and not (no_same_subbar_tp and lv in filled_this):
                            pf._close(trades, side, ebar[lv], entries[lv], estop, T, lv, j, "target", cost); done_legs.append(lv)
                            if records is not None:
                                records.append(s4._mk(lv, T, "target", j, entries, ebar, istop, side, cost, t4))
                            ret = (T - entries[lv]) if side == "long" else (entries[lv] - T)
                            if ret > 0:
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
        if not done:
            i += 1
    return trades


def submetrics(recs, fib):
    r = np.array([x["ret"] for x in recs if x["fib"] == fib])
    if len(r) == 0:
        return "0 сделок"
    pos = r[r > 0].sum(); neg = -r[r <= 0].sum()
    pf_ = pos / neg if neg > 0 else 9.99
    return f"n={len(r):>4} wr={(r>0).mean()*100:>3.0f}% exp={r.mean():+.3f} PF={min(pf_,9.99):.2f} сум={r.sum():+.0f}%"


def sysrow(name, trades):
    m = pf.metrics(trades, name)
    if m.get("n", 0) == 0:
        return f"{name:<16}{'нет':>6}"
    return f"{name:<16}n={m['n']:>4} wr={m['winrate_%']:>4}% exp={m['expectancy_%_per_trade']:>7} PF={str(m['profit_factor']):>5}"


def portrow(recs, ncoins, risk=1.0):
    a = rk.analyze(recs, risk, ncoins)
    if a is None:
        return "нет"
    return f"DD={a['mdd']:>6.1f}% Calmar={a['calmar']:>5.2f} итог={a['total']:>6.0f}% /год={a['ret_per_year']:>5.1f}%"


VARIANTS = [
    ("2 ноги (drop618)", dict(drop_leg3=True)),
    ("3н 618→ext(тек)",  dict(leg3_mode="ext")),
    ("3н 618→0.5",       dict(leg3_mode="0.5")),
    ("3н 618→0.382",     dict(leg3_mode="0.382")),
    ("3н 618→0.236",     dict(leg3_mode="0.236")),
]


def main():
    ds = {s: ib.load_15m_as_4h(os.path.join(DD, f"{s}_15m_cex.csv")) for s in COINS}

    # ── ГЕЙТ ВЕРНОСТИ: run_v4x(ext, без drop) == s4.run_v4 ──
    print("ГЕЙТ: run_v4x(leg3_mode='ext', drop_leg3=False) == s4.run_v4 (BTC+ETH, mbp=2.0, EMA200, stop1.0):")
    gate_ok = True
    for mbp in (2.0, 2.5):
        for sym, d in ds.items():
            a = [v2._tk(t) for t in s4.run_v4(d, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp)]
            b = [v2._tk(t) for t in run_v4x(d, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=mbp)]
            if a != b:
                print(f"  ✗ {sym} mbp{mbp}: {len(a)} vs {len(b)} — копия неверна"); gate_ok = False
    if not gate_ok:
        print("✗ Гейт не прошёл. Стоп."); sys.exit(1)
    print("✓ Гейт пройден: run_v4x верен, разница вариантов = чистый эффект ручки.\n")

    for mbp in (2.0, 2.5):
        for split, lo, hi in [("FULL 0-100%", 0.0, 1.0), ("IN-SAMPLE 0-60%", 0.0, 0.6), ("OUT-OF-SAMPLE 60-100%", 0.6, 1.0)]:
            print("=" * 100)
            print(f"min_bar={mbp} | {split} | BTC+ETH, 4h-сигнал/15m, стоп1.0, EMA200, RISK1%")
            print("=" * 100)
            for name, kw in VARIANTS:
                trades = []; recs = []
                for sym, d in ds.items():
                    p0 = max(int(len(d["c4"]) * lo), 2); p1 = int(len(d["c4"]) * hi)
                    trades += run_v4x(s4.slice_ds(d, p0, p1), 72, trend_ema=200, stop_fib=1.0,
                                      min_bar_pct=mbp, records=recs, **kw)
                print(f"{sysrow(name, trades)}")
                print(f"{'':<16}618: {submetrics(recs, 0.618)}")
                print(f"{'':<16}порт(1%): {portrow(recs, len(COINS))}")
            print()


if __name__ == "__main__":
    main()
