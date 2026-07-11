#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.1 — детектор «ДВА ТОЛЧКА через (необязательную) консолидацию» поверх лайфцикла V8 (пере-якорь до 0.5 + выходы V7).

ДЕТЕКТОР (лонг; шорт зеркально):
  - ТОЛЧОК 1 (бар i): ход >= mb1% И ЧИСТЫЙ (close в верхней половине: high-close < clean_thr*range — не самокорр.).
  - КОНСОЛИДАЦИЯ (0+ баров, НЕ обязательна): бары держатся выше середины бара1 (low > low1 + retr*range1)
    и СИДЯТ ПОД ХАЕМ бара1 (high <= high1) — строгий вариант. Пробой хая = это уже толчок 2.
  - ТОЛЧОК 2 (бар j, j>=i+1): ПЕРВЫЙ бар, пробивающий хай бара1 (high>high1). Должен быть сильным (>=mb2%) и ЧИСТЫМ.
    Если пробойный бар слабый/грязный — паттерн от бара1 отменяется (ищем новый импульс).
  - Откат >=retr внутри окна (low<=середина) — отмена. A=low бара1, B=high бара2.
  Частный случай 0 консолидации = два сильных чистых бара подряд (база).

ЛАЙФЦИКЛ и ВЫХОДЫ — как в V8/V7 (run_v8 с detect_fn): пере-якорь B до залива 0.5, затем машина V7.
2D-свип порогов mb1 × mb2 в [0.5..2.0] — ищем лучшую пару.
"""
import os, sys, numpy as np
from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_15m_intrabar as ib
from . import backtest_v4_sim as s4
from . import risk_sim as rk
from .v8_sim import run_v8
from .v7_sim import run_v7

from ._paths import DATA_DIR as DD
COINS = ["BTCUSDT", "ETHUSDT"]
_CACHE = {}
def _ds(s):
    if s not in _CACHE:
        _CACHE[s] = ib.load_15m_as_4h(os.path.join(DD, f"{s}_15m_cex.csv"))
    return _CACHE[s]


def detect_v81(o, h, l, c, i, mb1=1.0, mb2=0.7, retr=0.5, clean_thr=0.5, maxwin=0):
    n = len(c)
    if i < 1 or i >= n - 1:
        return None
    rng = h[i] - l[i]
    # ── LONG: бар1 сильный+чистый (close в верхней половине) ──
    if rng > 0 and rng / o[i] * 100.0 >= mb1 and (h[i] - c[i]) < clean_thr * rng:
        line = l[i] + retr * rng
        lim = (i + maxwin) if maxwin > 0 else n - 1
        j = i + 1
        while j <= lim and j < n:
            if l[j] < line:
                break                                  # откат >=50% бара1 -> отмена
            if h[j] > h[i]:                            # пробой хая бара1 = толчок 2 (первый такой)
                rj = h[j] - l[j]
                if rj > 0 and rj / o[j] * 100.0 >= mb2 and (h[j] - c[j]) < clean_thr * rj:
                    return ("long", l[i], h[j], j)      # сильный+чистый пробой
                break                                   # слабый/грязный пробой -> отмена
            j += 1                                       # иначе: консолидация под хаем -> дальше
    # ── SHORT (зеркально): бар1 close в нижней половине ──
    if rng > 0 and rng / o[i] * 100.0 >= mb1 and (c[i] - l[i]) < clean_thr * rng:
        line = h[i] - retr * rng
        lim = (i + maxwin) if maxwin > 0 else n - 1
        j = i + 1
        while j <= lim and j < n:
            if h[j] > line:
                break
            if l[j] < l[i]:
                rj = h[j] - l[j]
                if rj > 0 and rj / o[j] * 100.0 >= mb2 and (c[j] - l[j]) < clean_thr * rj:
                    return ("short", h[i], l[j], j)
                break
            j += 1
    return None


def run_v81(data, mb1=1.0, mb2=0.7, retr=0.5, clean_thr=0.5, max_window=0, **kw):
    df = lambda o, h, l, c, i: detect_v81(o, h, l, c, i, mb1, mb2, retr, clean_thr, max_window)
    return run_v8(data, detect_fn=df, **kw)


# ── ГЕЙТЫ ДЕТЕКТОРА ──
def gates():
    ok = True
    base = lambda: (np.array([100, 100], float), np.array([100.5, 100.5], float),
                    np.array([99.5, 99.5], float), np.array([100, 100], float))

    def mk(rows):  # rows: list of (o,h,l,c)
        o = np.array([100, 100] + [r[0] for r in rows], float)
        h = np.array([100.5, 100.5] + [r[1] for r in rows], float)
        l = np.array([99.5, 99.5] + [r[2] for r in rows], float)
        c = np.array([100, 100] + [r[3] for r in rows], float)
        return o, h, l, c
    # G1 база: два сильных чистых бара подряд (2-й новый хай) -> детект j=3
    o, h, l, c = mk([(100, 101.5, 100, 101.4), (101.4, 103, 101, 102.9)])
    r = detect_v81(o, h, l, c, 2, mb1=1.0, mb2=1.0)
    g1 = (r == ("long", 100.0, 103.0, 3))
    print(f"  G1 база (2 сильных подряд) -> ('long',100,103,3): {g1} | {r}"); ok = ok and g1
    # G2 импульс-консолидация-импульс: бар1, 2 консолидации под хаем, пробой -> j=5
    o, h, l, c = mk([(100, 101.5, 100, 101.4), (101.4, 101.4, 100.9, 101.0),
                     (101.0, 101.3, 100.85, 101.1), (101.1, 103, 101, 102.9)])
    r = detect_v81(o, h, l, c, 2, mb1=1.0, mb2=1.0)
    g2 = (r == ("long", 100.0, 103.0, 5))
    print(f"  G2 импульс-консолид-импульс -> j=5: {g2} | {r}"); ok = ok and g2
    # G3 откат >50% в консолидации -> None (low 100.7 < середина 100.75)
    o, h, l, c = mk([(100, 101.5, 100, 101.4), (101.4, 101.3, 100.7, 100.8), (100.8, 103, 101, 102.9)])
    r = detect_v81(o, h, l, c, 2, mb1=1.0, mb2=1.0)
    g3 = (r is None)
    print(f"  G3 откат >50% в консолид -> None: {g3} | {r}"); ok = ok and g3
    # G4 слабый пробой (range мал) -> None
    o, h, l, c = mk([(100, 101.5, 100, 101.4), (101.4, 103, 102.9, 102.95)])
    r = detect_v81(o, h, l, c, 2, mb1=1.0, mb2=1.0)
    g4 = (r is None)
    print(f"  G4 слабый пробой (range<mb2) -> None: {g4} | {r}"); ok = ok and g4
    # G5 грязный бар1 (самокорр., close внизу) -> None для лонга
    o, h, l, c = mk([(100, 101.5, 100, 100.3), (100.3, 103, 100.2, 102.9)])
    r = detect_v81(o, h, l, c, 2, mb1=1.0, mb2=1.0)
    g5 = (r is None) or (r[0] != "long")
    print(f"  G5 грязный бар1 -> не лонг: {g5} | {r}"); ok = ok and g5
    return ok


def metr(coins, kw, lo, hi):
    tr = []; rc = []
    for s in coins:
        d = _ds(s); p0 = max(int(len(d["c4"]) * lo), 2); p1 = int(len(d["c4"]) * hi)
        tr += run_v81(s4.slice_ds(d, p0, p1), records=rc, **kw)
    m = pf.metrics(tr, "x"); a = rk.analyze(rc, 1.0, len(coins))
    return m, a


def main():
    print("ГЕЙТЫ ДЕТЕКТОРА V8.1:")
    if not gates():
        print("✗ Гейты не прошли. Стоп."); sys.exit(1)
    print("✓ Гейты пройдены.\n")

    FIX = dict(leg2_ext=1.0, leg3_mode="0.382", stop_fib=1.0, trend_ema=200)
    GRID = [0.5, 0.7, 1.0, 1.25, 1.5, 1.75, 2.0]
    # V7 baseline
    rc7 = []
    for s in COINS:
        run_v7(_ds(s), 72, leg2_ext=1.0, leg3_mode="0.382", stop_fib=1.0, trend_ema=200, min_bar_pct=2.0, records=rc7)
    a7 = rk.analyze(rc7, 1.0, 2)
    print(f"V7 эталон (mbp2.0): FULL Calmar {a7['calmar']:.2f} итог {a7['total']:.0f}%\n")

    for split, lo, hi in [("FULL", 0.0, 1.0), ("OOS 60-100%", 0.6, 1.0)]:
        print("=" * 92)
        print(f"V8.1 · 2D-свип mb1×mb2 · {split} · BTC+ETH RISK1% · Calmar (n сделок)")
        print("=" * 92)
        print("mb1\\mb2 " + "".join(f"{m:>11}" for m in GRID))
        best = []
        for mb1 in GRID:
            row = [f"{mb1:>6}"]
            for mb2 in GRID:
                m, a = metr(COINS, dict(mb1=mb1, mb2=mb2, **FIX), lo, hi)
                cal = a["calmar"] if a else 0.0
                row.append(f"{cal:>6.2f}({m['n']:>4})")
                best.append((cal, mb1, mb2, m["n"], a["mdd"] if a else 0, a["total"] if a else 0))
            print("".join(row))
        best.sort(reverse=True)
        print(f"\n  Топ-5 {split} по Calmar:")
        for cal, mb1, mb2, n, mdd, tot in best[:5]:
            print(f"    mb1={mb1} mb2={mb2}: Calmar {cal:.2f}  n={n}  DD {mdd:.1f}%  итог {tot:.0f}%")
        print()


if __name__ == "__main__":
    main()
