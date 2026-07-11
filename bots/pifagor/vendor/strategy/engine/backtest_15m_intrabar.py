#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интрабар-проверка: тот же 4h-сигнал, но заливы/стоп/цель проверяются по 15m-барам
в реальном хронологическом порядке внутри каждого 4h-периода (разрешение в 16× мельче).
Цель — понять, не врёт ли 4h-бэктест из-за внутрибаровой неоднозначности (особенно у v2,
чьи выходы 0.5 сидят прямо в зоне отката). 15m есть только по BTC и ETH.

Не трогаем ни движок, ни backtest_v2_sim — переиспользуем их функции и политики.

ГЕЙТ: run_intrabar(coarse=True) [1 саб-бар = вся 4h-свеча] ОБЯЗАН посделочно совпасть
с проверенным v2.run_strategy() на ТЕХ ЖЕ собранных 4h-данных. Это доказывает, что
интрабар-машинерия верна и любая разница coarse↔fine — чисто эффект разрешения.
"""
import os
import sys
import numpy as np
import pandas as pd

from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_v2_sim as v2

FIB_ENTRIES = v2.FIB_ENTRIES


def load_15m_as_4h(path, tf="4h"):
    """15m CSV → (TF OHLC массивы) + (15m h/l массивы со смещениями по TF-периодам).
    tf — таймфрейм сигнала ('4h' по умолчанию, '1h' и т.п.); отработка всегда на 15m-саб-барах."""
    df = pf.load_csv(path)                      # time, open/high/low/close, sorted
    df = df.assign(p4=df["time"].dt.floor(tf))
    g = df.groupby("p4", sort=True)
    o4 = g["open"].first().to_numpy()
    h4 = g["high"].max().to_numpy()
    l4 = g["low"].min().to_numpy()
    c4 = g["close"].last().to_numpy()
    sizes = g.size().to_numpy()
    offs = np.zeros(len(sizes) + 1, dtype=np.int64)
    offs[1:] = np.cumsum(sizes)
    # начало 4h-бара в СЕКУНДАХ (устойчиво к us/ns-разрешению pandas)
    t4 = ((g["open"].first().index - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).to_numpy().astype(np.int64)
    return {
        "o4": o4, "h4": h4, "l4": l4, "c4": c4,
        "h15": df["high"].to_numpy(), "l15": df["low"].to_numpy(),
        "offs": offs, "t4": t4,
        "df4": pd.DataFrame({"open": o4, "high": h4, "low": l4, "close": c4}),
    }


def run_intrabar(data, max_wait, *, policy, cancel_on_new_high=False, coarse=False,
                 no_same_subbar_tp=False,
                 no_retrace=pf.IMPULSE_NO_RETRACE, min_bar_pct=pf.MIN_BAR_PCT,
                 stop_fib=pf.STOP_FIB, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT):
    o4, h4, l4, c4 = data["o4"], data["h4"], data["l4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    n = len(c4); cost = (fee + slip) / 100.0
    trades = []
    i = 2
    while i < n:
        imp = pf.detect_impulse(o4, h4, l4, c4, i, no_retrace, None, 0.0, min_bar_pct)
        if imp is None:
            i += 1; continue
        side, A, B = imp
        entries = {lv: pf.fib_price(A, B, lv, side) for lv in FIB_ENTRIES}
        stop = pf.fib_price(A, B, stop_fib, side)
        filled = {}; reached = {0.382: False, 0.5: False, 0.618: False}
        pending = False; done_setup = False; j = i + 1; wait = 0
        while j < n and not done_setup:
            if not filled:   # ратчет на 4h-периоде, только до первого залива
                if (side == "long" and h4[j] > B) or (side == "short" and l4[j] < B):
                    B = h4[j] if side == "long" else l4[j]
                    entries = {lv: pf.fib_price(A, B, lv, side) for lv in FIB_ENTRIES}
                    stop = pf.fib_price(A, B, stop_fib, side); wait = 0; j += 1; continue
            if cancel_on_new_high and filled and not pending:
                if (h4[j] > B) if side == "long" else (l4[j] < B):
                    pending = True
            if coarse:
                subs = [(h4[j], l4[j])]
            else:
                s, e = offs[j], offs[j + 1]
                subs = list(zip(h15[s:e], l15[s:e]))
            for hh, ll in subs:
                filled_this = []
                for lv in FIB_ENTRIES:
                    if lv in filled or pending:
                        continue
                    px = entries[lv]
                    if ll <= px <= hh:
                        filled[lv] = j; filled_this.append(lv)
                for lv in FIB_ENTRIES:
                    lvl = entries[lv]
                    if (ll <= lvl) if side == "long" else (hh >= lvl):
                        reached[lv] = True
                if filled:
                    stop_hit = (ll <= stop) if side == "long" else (hh >= stop)
                    done = []
                    for lv, ei in list(filled.items()):
                        tgt = pf.fib_price(A, B, policy(lv, reached), side)
                        tgt_hit = (hh >= tgt) if side == "long" else (ll <= tgt)
                        if stop_hit:
                            pf._close(trades, side, ei, entries[lv], stop, stop, lv, j, "stop", cost); done.append(lv)
                        elif tgt_hit and not (no_same_subbar_tp and lv in filled_this):
                            pf._close(trades, side, ei, entries[lv], stop, tgt, lv, j, "target", cost); done.append(lv)
                    for lv in done:
                        del filled[lv]
                    if done and not filled:
                        done_setup = True; i = j + 1; break
                    if stop_hit and not filled:
                        done_setup = True; i = j + 1; break
            if done_setup:
                break
            wait += 1
            if wait >= max_wait:
                for lv, ei in list(filled.items()):
                    pf._close(trades, side, ei, entries[lv], stop, c4[j], lv, j, "timeout", cost)
                done_setup = True; i = j + 1; break
            j += 1
        if not done_setup:
            i += 1
    return trades


VARIANTS = {
    "base":       dict(policy=v2.pol_base,       cancel_on_new_high=False),
    "v2_perleg":  dict(policy=v2.pol_v2_perleg,  cancel_on_new_high=True),
    "v2_uniform": dict(policy=v2.pol_v2_uniform, cancel_on_new_high=True),
}

COINS = ["BTCUSDT", "ETHUSDT"]


def main():
    data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    datasets = {}
    print("Загрузка 15m и сборка 4h:")
    for sym in COINS:
        path = os.path.join(data_dir, f"{sym}_15m_cex.csv")
        if not os.path.exists(path):
            print(f"  ⚠ нет {path}"); continue
        d = load_15m_as_4h(path); datasets[sym] = d
        # ГЕЙТ согласованности: 4h high/low == max/min его 15m саб-баров (группировка/смещения верны)
        hi = np.maximum.reduceat(d["h15"], d["offs"][:-1])
        lo = np.minimum.reduceat(d["l15"], d["offs"][:-1])
        if not (np.allclose(hi, d["h4"]) and np.allclose(lo, d["l4"])):
            print(f"  ✗ {sym}: 15m саб-бары не сходятся с 4h-баром — группировка сломана. Стоп."); sys.exit(1)
        print(f"  {sym}: 15m баров {len(d['h15'])}, собрано 4h-баров {len(d['c4'])}, согласованность 15m↔4h ✓")

    print("\nГЕЙТ — coarse-интрабар (1 саб-бар=вся 4h) == проверенный 4h-движок (на собранных 4h):")
    gate_ok = True
    for sym, d in datasets.items():
        for vname, kw in VARIANTS.items():
            for mw in (48, 72):
                a = [v2._tk(t) for t in v2.run_strategy(d["df4"], mw, **kw)]
                b = [v2._tk(t) for t in run_intrabar(d, mw, coarse=True, **kw)]
                if a != b:
                    print(f"  ✗ {sym}/{vname}/mw{mw}: coarse != 4h-движок ({len(a)} vs {len(b)})")
                    gate_ok = False
    if not gate_ok:
        print("\n✗ Гейт не прошёл. Стоп."); sys.exit(1)
    print("✓ Гейт пройден: интрабар-машинерия верна, разница coarse↔fine = чистый эффект разрешения.\n")

    for mw in (48, 72):
        print("=" * 86)
        print(f"4h-разрешение vs 15m-интрабар — MAX_WAIT={mw} (BTC+ETH агрегат)")
        print("=" * 86)
        hdr = (f"{'вариант':<12}"
               f"{'4h:эксп/сд':>12}{'4h:wr':>8}{'4h:PF':>7}   "
               f"{'15m:эксп/сд':>13}{'15m:wr':>8}{'15m:PF':>7}")
        print(hdr); print("-" * len(hdr))
        for vname, kw in VARIANTS.items():
            tr4, tr15 = [], []
            for sym, d in datasets.items():
                tr4 += run_intrabar(d, mw, coarse=True, **kw)
                tr15 += run_intrabar(d, mw, coarse=False, **kw)
            m4 = pf.metrics(tr4, vname); m15 = pf.metrics(tr15, vname)
            print(f"{vname:<12}"
                  f"{m4['expectancy_%_per_trade']:>12}{m4['winrate_%']:>7}%{str(m4['profit_factor']):>7}   "
                  f"{m15['expectancy_%_per_trade']:>13}{m15['winrate_%']:>7}%{str(m15['profit_factor']):>7}")
        print()


if __name__ == "__main__":
    main()
