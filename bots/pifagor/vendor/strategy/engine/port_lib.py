#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Портфельная библиотека (общий инструмент для воркфлоу-агентов).

10 монет, движок V8.1 (run_v8 + detect_v81 only-long), у каждой монеты свой размер бара.
Конфиг ноги: leg2_ext=1.0 (нога2→2.0, БУ), leg3_mode="0.382", stop_fib=1.0, EMA200, 4h/15m.

Инструменты:
  load()                         — загрузить/посчитать записи (кэш на диск _portcache.pkl)
  REC(s)/all_recs(coins)         — записи по монете / по портфелю
  compound(recs, risk, cap)      — компаунд по времени с лимитом одновременных ног (cap)
  walk_forward(coins,risk,cap)   — честный walk-forward (склейка тест-кусков), компаунд с капом
  risk_for_dd(coins,target,cap)  — подобрать риск под целевую wf-DD (%)
  concurrency(coins)             — макс одновременно открытых ног + ряд во времени
  bootstrap_dd(factors,...)      — блок-бутстрап распределения maxDD (P50/P90/P95/P99/worst)
  window_dd(curve, t0, t1)       — просадка equity-кривой в календарном окне [t0,t1] (epoch s)

Каждая запись: ret(%), stopdist, t_in, t_out (epoch сек), fib.
"""
import os, heapq, pickle, numpy as np
from . import backtest_15m_intrabar as ib, backtest_v4_sim as s4
from .v8_sim import run_v8
from .v81_sim import detect_v81

from ._paths import DATA_DIR as DD
BARS = {"BTCUSDT": (1.5, 2.5), "ETHUSDT": (1.5, 2.5), "BNBUSDT": (1.5, 5.0), "DOGEUSDT": (2.0, 5.0),
        "XRPUSDT": (2.0, 3.5), "ADAUSDT": (2.0, 3.5), "SOLUSDT": (3.0, 3.5), "LINKUSDT": (1.5, 5.0),
        "LTCUSDT": (2.0, 5.0), "ATOMUSDT": (3.0, 5.0)}
GRP = {"BTCUSDT": "майор", "ETHUSDT": "майор", "BNBUSDT": "биржевой", "DOGEUSDT": "мем",
       "XRPUSDT": "платёж", "LTCUSDT": "платёж", "SOLUSDT": "L1", "ADAUSDT": "L1",
       "ATOMUSDT": "L1", "LINKUSDT": "DeFi"}
COINS = list(BARS)
_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_portcache.pkl")

_DS = {}      # OHLC по монете (тяжёлое, лениво)
_REC = {}     # полные записи по монете
_WF = {}      # кэш walk-forward записей: (tuple(coins), nf) -> recs


def _longdet(a, b):
    def f(o, h, l, c, i):
        r = detect_v81(o, h, l, c, i, a, b)
        return None if r is None or r[0] != "long" else r
    return f


def run_coin(d, a, b, ema4_override=None, causal=True):
    # causal=True — причинный пере-якорь на 15m (фикс look-ahead #4); ema4_override — тёплая EMA (фикс #5).
    rc = []
    run_v8(d, detect_fn=_longdet(a, b), leg2_ext=1.0, leg3_mode="0.382",
           stop_fib=1.0, trend_ema=200, records=rc, ema4_override=ema4_override, causal_reanchor=causal)
    return rc


def _ds(s):
    if s not in _DS:
        _DS[s] = ib.load_15m_as_4h(os.path.join(DD, f"{s}_15m_cex.csv"))
    return _DS[s]


_EMA = {}  # тёплая EMA200 на полной серии монеты (для нарезки под WF-куски)


def _ema(s):
    if s not in _EMA:
        import pandas as pd
        _EMA[s] = pd.Series(_ds(s)["c4"]).ewm(span=200, adjust=False).mean().to_numpy()
    return _EMA[s]


def _wf_recs(coins, nf):
    key = (tuple(coins), nf)
    if key not in _WF:
        b = [i / nf for i in range(nf + 1)]
        recs = []
        for i in range(1, nf):
            for s in coins:
                d = _ds(s); p0 = max(int(len(d["c4"]) * b[i]), 2); p1 = int(len(d["c4"]) * b[i + 1])
                recs += run_coin(s4.slice_ds(d, p0, p1), *BARS[s], ema4_override=_ema(s)[p0:p1])
        _WF[key] = recs
    return _WF[key]


def load():
    """Загрузить записи (с диск-кэша, иначе посчитать и сохранить)."""
    if _REC:
        return
    if os.path.exists(_CACHE):
        d = pickle.load(open(_CACHE, "rb"))
        _REC.update(d["REC"]); _WF.update(d["WF"])
        return
    for s in COINS:
        _REC[s] = run_coin(_ds(s), *BARS[s])
    _WF[(tuple(COINS), 6)] = _wf_recs(COINS, 6)
    pickle.dump({"REC": _REC, "WF": _WF}, open(_CACHE, "wb"))


def REC(s=None):
    load(); return _REC if s is None else _REC[s]


def all_recs(coins=None):
    load(); coins = coins or COINS
    return [r for s in coins for r in _REC[s]]


def compound(recs, risk, cap=None):
    """Компаунд по времени. cap=макс одновременно открытых ног (None=∞); сверх капа нога ПРОПУСКАЕТСЯ.
    Размер ноги = min(5, risk/stopdist) (плечо-cap 5x), PnL применяется при выходе. Возвращает кривую и факторы."""
    legs = sorted(recs, key=lambda r: r["t_in"])
    if not legs:
        return None
    h = []; E = 10000.0; peak = E; mdd = 0.0; skipped = 0; seq = 0
    factors = []; curve = []

    def close_until(t):
        nonlocal E, peak, mdd
        while h and h[0][0] <= t:
            to, _, frac, ret = heapq.heappop(h)
            f = frac * ret / 100.0
            E *= (1 + f); peak = max(peak, E); mdd = min(mdd, (E - peak) / peak)
            factors.append(f); curve.append((to, E))

    for r in legs:
        close_until(r["t_in"])
        if cap is not None and len(h) >= cap:
            skipped += 1; continue
        frac = min(5.0, risk / r["stopdist"] if r["stopdist"] > 0 else 5.0)
        seq += 1; heapq.heappush(h, (r["t_out"], seq, frac, r["ret"]))
    close_until(float("inf"))
    yrs = (legs[-1]["t_out"] - legs[0]["t_in"]) / 86400 / 365
    return {"cagr": (E / 10000.0) ** (1 / max(yrs, .01)) - 1, "mdd": mdd * 100, "end": E,
            "n": len(legs) - skipped, "skipped": skipped, "yrs": yrs,
            "factors": np.array(factors), "curve": curve}


def walk_forward(coins, risk, cap=None, nf=6):
    return compound(_wf_recs(list(coins), nf), risk, cap)


def risk_for_dd(coins, target_dd, cap=None, nf=6, lo=0.05, hi=12.0):
    """Бисекция риска под целевую |wf-DD| (%)."""
    for _ in range(30):
        mid = (lo + hi) / 2
        if abs(walk_forward(coins, mid, cap, nf)["mdd"]) > target_dd:
            hi = mid
        else:
            lo = mid
    return mid, walk_forward(coins, mid, cap, nf)


def concurrency(coins=None):
    recs = all_recs(coins); iv = sorted((r["t_in"], r["t_out"]) for r in recs)
    h = []; mx = 0; series = []
    for ti, to in iv:
        heapq.heappush(h, to)
        while h and h[0] < ti:
            heapq.heappop(h)
        mx = max(mx, len(h)); series.append((ti, len(h)))
    return mx, series


def bootstrap_dd(factors, block=20, nsims=2000, seed=0):
    """Блок-бутстрап maxDD на серии мультипликативных факторов (сохраняет кластеры)."""
    rng = np.random.default_rng(seed)
    fr = np.asarray(factors); n = len(fr)
    if n < block * 3:
        return None
    nb = n // block; dds = []
    for _ in range(nsims):
        idx = rng.integers(0, n - block, size=nb)
        seq = np.concatenate([fr[i:i + block] for i in idx])
        E = 1.0; peak = 1.0; mdd = 0.0
        for f in seq:
            E *= (1 + f); peak = max(peak, E); mdd = min(mdd, (E - peak) / peak)
        dds.append(-mdd * 100)
    dds = np.array(dds)
    return {"p50": float(np.percentile(dds, 50)), "p90": float(np.percentile(dds, 90)),
            "p95": float(np.percentile(dds, 95)), "p99": float(np.percentile(dds, 99)),
            "worst": float(dds.max())}


def window_dd(curve, t0, t1):
    """Макс просадка equity-кривой [(t,E)] внутри календарного окна [t0,t1] (epoch s)."""
    pts = [(t, E) for t, E in curve if t0 <= t <= t1]
    if len(pts) < 2:
        return None
    peak = pts[0][1]; mdd = 0.0
    for t, E in pts:
        peak = max(peak, E); mdd = min(mdd, (E - peak) / peak)
    return mdd * 100


if __name__ == "__main__":
    import time
    t = time.time(); load(); print(f"load {time.time()-t:.1f}s, монет {len(_REC)}, всего записей {sum(len(v) for v in _REC.values())}")
    for rk in [0.5, 1.0, 1.5, 2.0]:
        m = walk_forward(COINS, rk)
        print(f"  risk {rk}: CAGR {m['cagr']*100:.0f}% wf-DD {m['mdd']:.0f}% ${m['end']:,.0f}")
    mx, _ = concurrency(); print(f"  макс одновременных ног: {mx}")
    r, m = risk_for_dd(COINS, 20.0); print(f"  риск под wf-DD20%: {r:.2f}% → CAGR {m['cagr']*100:.0f}%")
    bs = bootstrap_dd(walk_forward(COINS, 1.25)["factors"]); print(f"  bootstrap risk1.25 wf: P50 {bs['p50']:.0f}% P95 {bs['p95']:.0f}% worst {bs['worst']:.0f}%")
    print("OK")
