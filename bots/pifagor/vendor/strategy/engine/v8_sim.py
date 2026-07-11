#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PIFAGOR V8 — мультибаровый импульс + пере-якорь до 0.5 + выходы V7.

ДЕТЕКТОР (мультибар, зеркально long/short):
  - бар 1 = старт (A = его low для long). Сильный и ЧИСТЫЙ: range >= min_bar%, close в верхней половине
    (для long: high-close < clean_thr*range — нет самокоррекции хвостом).
  - окно: любые внутренние бары, НИ ОДИН не откатывает бар 1 на >= retr (по hi-lo): low > low1 + retr*range1.
  - подтверждение: какой-то бар окна обновляет хай бара 1 (high > high1) -> B = его хай, jc = его индекс.
  - min_bar_scope: "bar1" (сильным должен быть бар1) | "any" (хотя бы один бар окна сильный+чистый).

ЛАЙФЦИКЛ (отличие от V7):
  - ставим сетку 0.382/0.5/0.618 от (A,B). ПЕРЕ-ЯКОРЬ: пока 0.5 не залита (не committed) и нет открытой 0.382,
    любой новый хай (h4>B) -> B=новый хай, сетка перерисовывается (старые pending сняты; реализованные 0.382 остаются).
  - пре-commit заливается только 0.382 (до 0.5 не дойти не зайдя в commit). 0.382 -> скальп 0.236 (как V7 одиночная).
  - как только залита 0.5 -> committed=True, пере-якоря больше нет, дальше МАШИНА ВЫХОДОВ V7
    (шок/лесенка: нога2->ext(leg2_ext), нога3->leg3_mode, мелкие скальп), таймаут 72 (с момента commit).
  - profit_taken/beyond_B сбрасываются на каждом пере-якоре (новая сетка).

Гейты: синтетика детектора (G1-G3) + дымовой прогон BTC+ETH. Полную прокатку НЕ делаем здесь.
"""
import os, sys, numpy as np, pandas as pd
from . import pifagor_fib_backtest_v2_clean as pf
from . import backtest_15m_intrabar as ib
from . import backtest_v4_sim as s4
from . import risk_sim as rk
from .leg3_exit_test import submetrics, sysrow, portrow
from .v7_sim import run_v7

from ._paths import DATA_DIR as DD
LV = [0.382, 0.5, 0.618]
NEXT_SCALP = s4.NEXT_SCALP


def detect_v8(o, h, l, c, i, retr=0.5, min_bar=2.0, clean=True, clean_thr=0.5,
              require_dir=True, scope="bar1", maxwin=0):
    n = len(c)
    if i < 1 or i >= n - 1:
        return None
    # ── LONG ──
    if (not require_dir) or (c[i] > o[i]):
        rng = h[i] - l[i]
        if rng > 0:
            ok = True
            if scope == "bar1":
                if rng / o[i] * 100.0 < min_bar:
                    ok = False
                if clean and (h[i] - c[i]) >= clean_thr * rng:
                    ok = False
            if ok:
                line = l[i] + retr * rng
                strong = (scope == "bar1")
                lim = (i + maxwin) if maxwin > 0 else n - 1
                j = i + 1
                while j <= lim and j < n:
                    if l[j] < line:
                        break
                    if scope == "any":
                        rj = h[j] - l[j]
                        if rj > 0 and rj / o[j] * 100.0 >= min_bar and (not clean or (h[j] - c[j]) < clean_thr * rj):
                            strong = True
                    if h[j] > h[i] and strong:
                        return ("long", l[i], h[j], j)
                    j += 1
    # ── SHORT (зеркально) ──
    if (not require_dir) or (c[i] < o[i]):
        rng = h[i] - l[i]
        if rng > 0:
            ok = True
            if scope == "bar1":
                if rng / o[i] * 100.0 < min_bar:
                    ok = False
                if clean and (c[i] - l[i]) >= clean_thr * rng:
                    ok = False
            if ok:
                line = h[i] - retr * rng
                strong = (scope == "bar1")
                lim = (i + maxwin) if maxwin > 0 else n - 1
                j = i + 1
                while j <= lim and j < n:
                    if h[j] > line:
                        break
                    if scope == "any":
                        rj = h[j] - l[j]
                        if rj > 0 and rj / o[j] * 100.0 >= min_bar and (not clean or (c[j] - l[j]) < clean_thr * rj):
                            strong = True
                    if l[j] < l[i] and strong:
                        return ("short", h[i], l[j], j)
                    j += 1
    return None


def run_v8(data, *, retr=0.5, min_bar_pct=2.0, clean=True, clean_thr=0.5, require_dir=True,
           min_bar_scope="bar1", max_window=0, commit_lv=0.5, detect_fn=None,
           leg2_ext=1.0, leg3_mode="0.382", stop_fib=1.0, trend_ema=200, max_wait=72,
           no_same_subbar_tp=True, records=None, shock_events=None, ema4_override=None, causal_reanchor=False, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT,
           reanchor_after_scalp=False, cond05=None, tol05=0.0, trail_r=0.0, trail_diag=None):
    o4, h4, l4, c4 = data["o4"], data["h4"], data["l4"], data["c4"]
    h15, l15, offs = data["h15"], data["l15"], data["offs"]
    t4 = data.get("t4"); n = len(c4); cost = (fee + slip) / 100.0
    # ema4_override — тёплая EMA, посчитанная на ПОЛНОЙ серии и нарезанная под этот срез (фикс #5: холодный старт EMA на WF-кусках)
    ema4 = (ema4_override if ema4_override is not None
            else (pd.Series(c4).ewm(span=trend_ema, adjust=False).mean().to_numpy() if trend_ema > 0 else None))
    trades = []
    i = 2
    while i < n - 1:
        imp = (detect_fn(o4, h4, l4, c4, i) if detect_fn is not None
               else detect_v8(o4, h4, l4, c4, i, retr, min_bar_pct, clean, clean_thr, require_dir, min_bar_scope, max_window))
        if imp is None:
            i += 1; continue
        side, A, B, jc = imp
        if ema4 is not None and not np.isnan(ema4[jc]):
            up = c4[jc] > ema4[jc]
            if (side == "long" and not up) or (side == "short" and up):
                i = jc + 1; continue
        lp = lambda L: pf.fib_price(A, B, L, side)
        ext = lambda m: pf.fib_price(A, B, -m, side)
        entries = {lv: lp(lv) for lv in LV}; stop0 = lp(stop_fib)
        state = {lv: "pending" for lv in LV}; ebar = {}; istop = {}
        profit_taken = False; beyond_B = False; committed = False; spring_recorded = False; leg1_scalped = False
        peak = B   # R8-трейл: running-high/low с момента сетапа (для trail_r)
        done = False; k = jc + 1; wait = 0

        def emit(lv, expx, oc, jbar):
            pf._close(trades, side, ebar[lv], entries[lv], istop.get(lv, stop0), expx, lv, jbar, oc, cost)
            if records is not None:
                records.append(s4._mk(lv, expx, oc, jbar, entries, ebar, istop, side, cost, t4))

        while k < n and not done:
            # ── ПРЕ-COMMIT: пере-якорь по ПОЛНОМУ 4h-бару (старое поведение, look-ahead #4) ──
            if (not causal_reanchor) and not committed and state[0.382] != "open":
                newhigh = (h4[k] > B) if side == "long" else (l4[k] < B)
                if newhigh:
                    B = h4[k] if side == "long" else l4[k]
                    entries = {lv: lp(lv) for lv in LV}; stop0 = lp(stop_fib)
                    state = {lv: "pending" for lv in LV}; ebar = {}; istop = {}
                    profit_taken = False; beyond_B = False; leg1_scalped = False; peak = B
                    k += 1; continue
            s, e = offs[k], offs[k + 1]
            for hh, ll in zip(h15[s:e], l15[s:e]):
                filled_this = []
                for lv in LV:
                    if state[lv] != "pending":
                        continue
                    thr = entries[lv]
                    if lv == 0.5 and cond05 == "double_dip" and tol05 > 0.0 and leg1_scalped:
                        thr = entries[0.5] + tol05 * abs(B - A)   # двойной заход: сдвиг порога 0.5 вверх
                    if ll <= thr <= hh:
                        state[lv] = "open"; ebar[lv] = k; filled_this.append(lv); istop[lv] = stop0
                        if lv == 0.5 and thr != entries[0.5]:
                            entries[0.5] = thr                    # запись ХУДШЕЙ цены входа
                # ── ПРИЧИННЫЙ пере-якорь (#4 фикс) + v3 «пере-якорь после скальпа» (reanchor_after_scalp) ──
                # Гейт «no_open + not filled_this»: пере-якорь НИКОГДА не по хаю суб-бара с заливом (залитая нога=open).
                # reanchor_after_scalp=False ⇒ якорь ЗАМОРАЖИВАЕТСЯ на первом заливе (v2, инвариант #9, бит-в-бит).
                # True/"any" ⇒ v3: перезаряжает закрытую скальп-ногу на новый хай; "win" ⇒ только после плюсового скальпа.
                if causal_reanchor and not committed and not filled_this \
                        and not any(state[lv] == "open" for lv in LV):
                    _has_closed = any(state[lv] == "closed" for lv in LV)
                    if not _has_closed:
                        _allow = True                                  # all-pending пере-якорь (== v2/заморозка)
                    elif reanchor_after_scalp == "win":
                        _allow = profit_taken
                    elif reanchor_after_scalp:                         # True / "any"
                        _allow = True
                    else:
                        _allow = False                                 # v2: закрытый скальп замораживает якорь
                    if _allow and ((hh > B) if side == "long" else (ll < B)):
                        B = hh if side == "long" else ll
                        entries = {lv: lp(lv) for lv in LV}; stop0 = lp(stop_fib)
                        state = {lv: "pending" for lv in LV}; ebar = {}; istop = {}   # ре-арм (no-op если all-pending)
                        profit_taken = False; beyond_B = False; leg1_scalped = False; peak = B   # double-dip: сброс латча на ре-якоре (блокер-фикс)
                        continue
                if (hh > B) if side == "long" else (ll < B):
                    beyond_B = True
                if not committed and state[commit_lv] == "open":
                    committed = True; wait = 0
                open_legs = [lv for lv in LV if state[lv] == "open"]
                if open_legs:
                    if not committed:
                        # пре-commit: открыта только 0.382 -> защитный скальп 0.236
                        for lv in list(open_legs):
                            T, estop = lp(0.236), stop0
                            sh = (ll <= estop) if side == "long" else (hh >= estop)
                            th = (hh >= T) if side == "long" else (ll <= T)
                            if sh:
                                emit(lv, estop, "stop", k); state[lv] = "closed"
                            elif th and not (no_same_subbar_tp and lv in filled_this):
                                emit(lv, T, "target", k); state[lv] = "closed"
                                if ((T - entries[lv]) if side == "long" else (entries[lv] - T)) > 0:
                                    profit_taken = True
                                if lv == 0.382:
                                    leg1_scalped = True           # нога 0.382 сняла скальп → взвести латч double-dip
                    else:
                        # ── POST-COMMIT: машина выходов V7 ──
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
                                if trail_r > 0.0 and beyond_B:   # R8-трейл: фикс-цель → трейл-стоп peak−trail_r·R (только за B)
                                    trail = peak - trail_r * (B - A) if side == "long" else peak + trail_r * (B - A)
                                    estop = max(estop, trail) if side == "long" else min(estop, trail)
                                    T = 1e12 if side == "long" else -1e12   # снять фикс-цель: выход ведёт трейл
                            istop_eff = estop
                            sh = (ll <= estop) if side == "long" else (hh >= estop)
                            th = (hh >= T) if side == "long" else (ll <= T)
                            if sh:
                                _fx = (min(estop, hh) if side == "long" else max(estop, ll))   # реалистичный филл: стоп не выше бара (важно для трейла)
                                if ride and trail_r > 0.0 and trail_diag is not None:   # ДИАГ: докуда дошёл пик (в R за вершиной B) + где вышли
                                    _R = (B - A) or 1.0
                                    trail_diag.append({"peak_r": ((peak - B) / _R) if side == "long" else ((B - peak) / _R),
                                                       "exit_r": ((_fx - B) / _R) if side == "long" else ((B - _fx) / _R)})
                                emit2(trades, records, side, ebar, entries, istop, lv, _fx, "stop", k, cost, t4); done_legs.append(lv)
                                if shock and shock_events is not None and not spring_recorded:
                                    shock_events.append({"A": A, "B": B, "side": side, "bar": k}); spring_recorded = True
                            elif th and not (no_same_subbar_tp and lv in filled_this):
                                emit2(trades, records, side, ebar, entries, istop, lv, T, "target", k, cost, t4); done_legs.append(lv)
                                if ((T - entries[lv]) if side == "long" else (entries[lv] - T)) > 0:
                                    profit_taken = True
                        for lv in done_legs:
                            state[lv] = "closed"
                if trail_r > 0.0:   # R8-трейл: 15m-пик — обновить ПОСЛЕ проверки выхода этого суб-бара (causal)
                    peak = max(peak, hh) if side == "long" else min(peak, ll)
                if committed and profit_taken and beyond_B and not any(state[lv] == "open" for lv in LV):
                    done = True; i = k + 1; break
                if committed and all(state[lv] == "closed" for lv in LV):
                    done = True; i = k + 1; break
            if done:
                break
            if committed:
                wait += 1
                if wait >= max_wait:
                    for lv in LV:
                        if state[lv] == "open":
                            emit2(trades, records, side, ebar, entries, istop, lv, c4[k], "timeout", k, cost, t4)
                    done = True; i = k + 1; break
            k += 1
        if not done:
            # конец данных: закрыть открытые по последнему close
            for lv in LV:
                if state[lv] == "open":
                    emit2(trades, records, side, ebar, entries, istop, lv, c4[n - 1], "eod", n - 1, cost, t4)
            i = max(jc + 1, i + 1)
    return trades


def emit2(trades, records, side, ebar, entries, istop, lv, expx, oc, jbar, cost, t4):
    pf._close(trades, side, ebar[lv], entries[lv], istop.get(lv, expx), expx, lv, jbar, oc, cost)
    if records is not None:
        records.append(s4._mk(lv, expx, oc, jbar, entries, ebar, istop, side, cost, t4))


# ── СИНТЕТИЧЕСКИЕ ГЕЙТЫ ДЕТЕКТОРА ──
def gates():
    ok = True
    # G1: мультибар-импульс детектится (бар1 сильный/чистый, 2 внутренних держатся, 5-й новый хай)
    o = np.array([100, 100, 100, 104, 102.8, 103.5], float)
    h = np.array([101, 101, 104.2, 104.1, 104.0, 106.0], float)
    l = np.array([99, 99, 100, 102.5, 102.3, 103.0], float)
    c = np.array([100, 100, 104, 102.8, 103.5, 105.8], float)
    r = detect_v8(o, h, l, c, 2)
    g1 = (r is not None and r[0] == "long" and abs(r[1] - 100) < 1e-9 and abs(r[2] - 106.0) < 1e-9 and r[3] == 5)
    print(f"  G1 мультибар-детект (long A=100 B=106 jc=5): {g1} | got={r}"); ok = ok and g1
    # G2: откат >50% бара1 отменяет (внутренний low 101.9 < 102.1)
    l2 = l.copy(); l2[3] = 101.9
    r2 = detect_v8(o, h, l2, c, 2)
    g2 = (r2 is None) or (r2[3] != 5)
    print(f"  G2 откат >50% отменяет импульс: {g2} | got={r2}"); ok = ok and g2
    # G3: самокорректирующийся бар1 (close в нижней половине) отвергнут
    c3 = c.copy(); c3[2] = 101.0   # бар1 close=101: h-c=3.2 >= 0.5*4.2=2.1 -> самокорр
    r3 = detect_v8(o, h, l, c3, 2)
    g3 = (r3 is None) or (r3[3] != 5)   # из i=2 не должен стартовать
    print(f"  G3 самокорр. бар1 отвергнут: {g3} | got={r3}"); ok = ok and g3
    return ok


def main():
    print("ГЕЙТЫ ДЕТЕКТОРА V8 (синтетика):")
    if not gates():
        print("✗ Гейты не прошли. Стоп."); sys.exit(1)
    print("✓ Гейты пройдены.\n")

    print("ДЫМОВОЙ ПРОГОН (BTC+ETH, дефолт V8: retr0.5 mbp2.0 clean bar1, нога2->2.0, нога3->0.382, EMA200, stop1.0):")
    coins = ["BTCUSDT", "ETHUSDT"]
    ds = {s: ib.load_15m_as_4h(os.path.join(DD, f"{s}_15m_cex.csv")) for s in coins}
    tr8 = []; rc8 = []; tr7 = []; rc7 = []
    for s in coins:
        d = ds[s]
        tr8 += run_v8(d, records=rc8)
        tr7 += run_v7(d, 72, trend_ema=200, stop_fib=1.0, min_bar_pct=2.0, leg2_ext=1.0, leg3_mode="0.382", records=rc7)
    m8 = pf.metrics(tr8, "v8"); m7 = pf.metrics(tr7, "v7")
    print(f"  V8: сделок={m8['n']}  exp={m8['expectancy_%_per_trade']}  PF={m8['profit_factor']}  wr={m8['winrate_%']}%")
    print(f"      порт(1%): {portrow(rc8, 2)}")
    print(f"  V7(=для сравнения): сделок={m7['n']}  exp={m7['expectancy_%_per_trade']}  PF={m7['profit_factor']}")
    print(f"      порт(1%): {portrow(rc7, 2)}")
    print(f"\n  (V8 даёт {'БОЛЬШЕ' if m8['n']>m7['n'] else 'не больше'} сигналов: {m8['n']} vs {m7['n']})")


if __name__ == "__main__":
    main()
