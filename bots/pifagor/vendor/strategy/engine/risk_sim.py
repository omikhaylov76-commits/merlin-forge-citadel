#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Портфельный риск-симулятор v4 (фильтр min_bar=2.0, 15m, net-of-fees).
- Реальный сайзинг: R = ret / начальная_дистанция_стопа; P&L ноги = min(RISK_PCT/stopdist, плечо) * ret  (% суб-баланса).
- Каждая монета = свой суб-баланс (1/N пула). Кривая капитала в КАЛЕНДАРНОМ времени (учёт корреляции/кластеров).
- Метрики: итог %пула, макс. просадка %пула, худший день, пиковый одновременный риск-он.
- Сетка RISK_PCT {1, 1.5, 2}; наборы: вся корзина (10) и крупные (BTC/ETH/DOGE/VET).
ВНИМАНИЕ: просадка additive (сумма %), без компаундинга — ок для характеристики риска.
"""
import os, glob, numpy as np
from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_15m_intrabar as ib
from . import backtest_v4_sim as s4

from ._paths import DATA_DIR as DD
MW = 72; MINBAR = 2.0; MAXLEV = 5  # config.MAX_LEVERAGE
LARGE = ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "VETUSDT"]
def _allc():
    return [os.path.basename(f).replace("_15m_cex.csv", "") for f in sorted(glob.glob(os.path.join(DD, "*_15m_cex.csv")))]

DSCACHE = {}
def load(sym):
    if sym not in DSCACHE:
        DSCACHE[sym] = ib.load_15m_as_4h(os.path.join(DD, f"{sym}_15m_cex.csv"))
    return DSCACHE[sym]

def records_for(coins):
    out = []
    for sym in coins:
        r = []
        s4.run_v4(load(sym), MW, min_bar_pct=MINBAR, records=r)
        out += r
    return out

DAY = 86400   # t4 в секундах

def analyze(recs, risk_pct, n):
    """Кривая капитала (книжим P&L по t_out), просадка, худший день, пиковый риск-он."""
    ev = []          # (t_out, pnl_%пула)
    risk_ev = []     # (t_in,+риск),(t_out,-риск) для heat
    for r in recs:
        d = r["stopdist"]
        nps = MAXLEV if d <= 0 else min(risk_pct / d, MAXLEV)   # номинал/суб
        pnl_pool = nps * r["ret"] / n                            # % пула
        ev.append((r["t_out"], pnl_pool))
        risk_leg = (risk_pct if d > 0 and risk_pct <= MAXLEV * d else MAXLEV * d) / n  # макс. потеря ноги, %пула
        risk_ev.append((r["t_in"], risk_leg)); risk_ev.append((r["t_out"] + 1, -risk_leg))
    if not ev:
        return None
    ev.sort()
    eq = pk = mdd = 0.0
    daily = {}
    for t, p in ev:
        eq += p; pk = max(pk, eq); mdd = min(mdd, eq - pk)
        daily[t // DAY] = daily.get(t // DAY, 0.0) + p
    risk_ev.sort()
    cur = hmax = 0.0
    for t, dv in risk_ev:
        cur += dv; hmax = max(hmax, cur)
    span_days = (ev[-1][0] - ev[0][0]) / DAY
    years = max(span_days / 365.0, 0.01)
    return {"n": len(ev), "total": eq, "mdd": mdd, "worst_day": min(daily.values()),
            "heat": hmax, "ret_per_year": eq / years, "calmar": (eq / years) / abs(mdd) if mdd < 0 else 9.99}


def main():
    for label, coins in [("ВСЯ КОРЗИНА (10)", _allc()), ("КРУПНЫЕ (BTC/ETH/DOGE/VET)", LARGE)]:
        recs = records_for(coins); n = len(coins)
        print("=" * 78)
        print(f"{label} — v4, min_bar={MINBAR}, {n} суб-баланса (каждый = 1/{n} пула)")
        print("=" * 78)
        print(f"{'RISK%':>6}{'итог%пула':>11}{'/год%':>9}{'макс.DD%':>10}{'худш.день%':>12}{'пик риск-он%':>14}{'Calmar':>8}")
        for rp in [1.0, 1.5, 2.0]:
            m = analyze(recs, rp, n)
            print(f"{rp:>6}{m['total']:>11.0f}{m['ret_per_year']:>9.1f}{m['mdd']:>10.1f}{m['worst_day']:>12.2f}{m['heat']:>14.2f}{m['calmar']:>8.2f}")
        print()


if __name__ == "__main__":
    main()
