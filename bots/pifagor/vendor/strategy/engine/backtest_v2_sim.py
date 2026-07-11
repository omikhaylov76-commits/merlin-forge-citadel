#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Симулятор сравнения ПРАВИЛ ВЫХОДА на истории. Проверенный движок не трогаем:
импортируем detect_impulse / fib_price / _close / metrics / load_csv и КОНСТАНТЫ —
вход/стоп/издержки/детект идентичны во всех вариантах, различается ТОЛЬКО политика выхода.

Политика выхода = функция policy(lv, reached) -> уровень фибо для цели залитой ноги.
  reached = {0.382:bool, 0.5:bool, 0.618:bool} — самые глубокие достигнутые уровни отката.
  lv      = уровень входа ноги (0.382/0.5/0.618).
Так разница «единый уровень на все ноги» vs «по-ногам» становится ЯВНОЙ и аудируемой
(замечание ревью №1: раньше de-risk применялся единым common_tgt ко всем ногам неявно).

Варианты:
  base        — точная копия движка: любая залитая нога целит в 0.236 (правило 0.5→0.236).
  v1_live     — как живой бот: фикс. цели FIB_TARGETS[lv], БЕЗ правила 0.5→0.236.
  v2_uniform  — БУКВАЛЬНО правила владельца: дошли до 0.618 → ВСЕ ноги на 0.5 (даже в минус); иначе 0.236.
  v2_nocancel — то же без снятия ноги на новом хае (изолирует эффект снятия).
  v2_perleg   — де-риск ТОЛЬКО глубокой ноги: нога 0.618 → 0.5; мелкие 0.382/0.5 → 0.236 (как база).
  v2_alt0382  — альтернатива владельца: на глубине 0.5 цель 0.382 (единым уровнем).

ГЕЙТЫ корректности:
  Г1: run_strategy(policy=base, cancel=False) == pf.run() посделочно (вход/выход = движок).
  Г2: на СИНТЕТИКЕ, реально доходящей до 0.618 с залитыми 0.382/0.5, v2_uniform ОБЯЗАН
      закрыть мелкую ногу 0.382 по 0.5 в МИНУС (исполняет de-risk-ветку), а v2_perleg —
      НЕ закрывать её по 0.5 (мелкая нога целит выше). Закрывает дыру покрытия (ревью №1).
"""
import sys
import numpy as np
import pandas as pd

from . import pifagor_fib_backtest_v2_clean as pf

FIB_ENTRIES = pf.FIB_ENTRIES            # [0.382, 0.5, 0.618]
FIB_TARGETS = pf.FIB_TARGETS            # {0.382:0.236, 0.5:0.382, 0.618:0.5}


# ── политики выхода ───────────────────────────────────────────────────────────
def pol_base(lv, reached):      return 0.236 if reached[0.5] else FIB_TARGETS[lv]
def pol_live(lv, reached):      return FIB_TARGETS[lv]
def pol_v2_uniform(lv, reached): return 0.5 if reached[0.618] else 0.236
def pol_v2_alt0382(lv, reached): return 0.5 if reached[0.618] else (0.382 if reached[0.5] else 0.236)
def pol_v2_perleg(lv, reached):
    if lv == 0.618: return 0.5
    return 0.236 if reached[0.5] else FIB_TARGETS[lv]
def pol_deriskoff(lv, reached): return 0.236   # контроль: == base на практике


def run_strategy(df, max_wait, *, policy, cancel_on_new_high=False,
                 no_retrace=pf.IMPULSE_NO_RETRACE, min_bar_pct=pf.MIN_BAR_PCT,
                 stop_fib=pf.STOP_FIB, fee=pf.FEE_PCT, slip=pf.SLIPPAGE_PCT):
    """Цикл 1-в-1 с pf.run (порядок: ратчет→заливы→reached→выходы→таймаут);
    различие только в policy(lv,reached) и опц. снятии ноги на новом хае."""
    o = df["open"].values; h = df["high"].values; l = df["low"].values; c = df["close"].values
    n = len(df); cost = (fee + slip) / 100.0
    trades = []
    i = 2
    while i < n:
        imp = pf.detect_impulse(o, h, l, c, i, no_retrace, None, 0.0, min_bar_pct)
        if imp is None:
            i += 1; continue
        side, A, B = imp
        entries = {lv: pf.fib_price(A, B, lv, side) for lv in FIB_ENTRIES}
        stop = pf.fib_price(A, B, stop_fib, side)
        filled = {}; reached = {0.382: False, 0.5: False, 0.618: False}
        pending_cancelled = False; setup_done = False
        j = i + 1; wait = 0
        while j < n and not setup_done:
            hj, lj = h[j], l[j]
            if not filled:   # ратчет B только до первого залива (как в движке)
                if side == "long" and hj > B:
                    B = hj; entries = {lv: pf.fib_price(A, B, lv, side) for lv in FIB_ENTRIES}
                    stop = pf.fib_price(A, B, stop_fib, side); wait = 0; j += 1; continue
                if side == "short" and lj < B:
                    B = lj; entries = {lv: pf.fib_price(A, B, lv, side) for lv in FIB_ENTRIES}
                    stop = pf.fib_price(A, B, stop_fib, side); wait = 0; j += 1; continue
            if cancel_on_new_high and filled and not pending_cancelled:
                if (hj > B) if side == "long" else (lj < B):
                    pending_cancelled = True
            for lv in FIB_ENTRIES:
                if lv in filled or pending_cancelled:
                    continue
                px = entries[lv]
                if lj <= px <= hj:
                    filled[lv] = j
            for lv in FIB_ENTRIES:
                lvl = entries[lv]
                if (lj <= lvl) if side == "long" else (hj >= lvl):
                    reached[lv] = True
            if filled:
                stop_hit = (lj <= stop) if side == "long" else (hj >= stop)
                done = []
                for lv, ei in list(filled.items()):
                    tgt_lv = policy(lv, reached)
                    tgt = pf.fib_price(A, B, tgt_lv, side)
                    tgt_hit = (hj >= tgt) if side == "long" else (lj <= tgt)
                    if stop_hit:
                        pf._close(trades, side, ei, entries[lv], stop, stop, lv, j, "stop", cost); done.append(lv)
                    elif tgt_hit:
                        pf._close(trades, side, ei, entries[lv], stop, tgt, lv, j, "target", cost); done.append(lv)
                for lv in done:
                    del filled[lv]
                if done and not filled:
                    setup_done = True; i = j + 1; break
                if stop_hit and not filled:
                    setup_done = True; i = j + 1; break
            wait += 1
            if wait >= max_wait:
                for lv, ei in list(filled.items()):
                    pf._close(trades, side, ei, entries[lv], stop, c[j], lv, j, "timeout", cost)
                setup_done = True; i = j + 1; break
            j += 1
        if not setup_done:
            i += 1
    return trades


def _tk(t):
    return (t.side, t.entry_i, t.exit_i, t.entry_fib, t.outcome, round(t.ret_pct, 6))


# ── ГЕЙТ 1: база == движок ────────────────────────────────────────────────────
def gate_baseline(df, label):
    for mw in (48, 72):
        a = [_tk(t) for t in pf.run(df, max_wait=mw)]
        b = [_tk(t) for t in run_strategy(df, mw, policy=pol_base)]
        if a != b:
            print(f"  ✗ {label} mw={mw}: база != движок ({len(a)} vs {len(b)})")
            return False
    return True


# ── ГЕЙТ 2: синтетика, реально исполняющая de-risk-ветку (0.618) ──────────────
def _synthetic_deep_df():
    """Лонг-импульс 100→120, затем лесенкой откат 0.382→0.5→0.618 и отскок к 0.5(=110).
    Уровни: 0.382=112.36, 0.5=110, 0.618=107.64, стоп 102."""
    bars = [
        (100, 100, 100, 100),  # 0 филлер
        (100, 110, 100, 109),  # 1 импульс-бар1 (бычий, range 10)
        (109, 120, 108, 119),  # 2 импульс-бар2 (новый хай, low>середина бар1=105) → A=100,B=120
        (113, 114, 112, 113),  # 3 откат к 0.382 (112.36 в [112,114]); хай<115.28 (не выходим)
        (112, 113, 109, 110),  # 4 откат к 0.5 (110 в [109,113]); хай<115.28
        (109, 109, 107, 108),  # 5 откат к 0.618 (107.64 в [107,109]); хай<110 (не выходим)
        (108, 111, 108, 110),  # 6 отскок: хай 111≥110 → выход всех по 0.5(=110)
    ]
    return pd.DataFrame([{"open": o, "high": h, "low": l, "close": c} for (o, h, l, c) in bars])


def gate_derisk_branch():
    df = _synthetic_deep_df()
    # min_bar_pct=0 чтобы фильтр шума не мешал синтетике
    tr_u = run_strategy(df, 48, policy=pol_v2_uniform, min_bar_pct=0.0)
    tr_p = run_strategy(df, 48, policy=pol_v2_perleg, min_bar_pct=0.0)
    # uniform: нога 0.382 ОБЯЗАНА закрыться по цели (0.5=110) в МИНУС — де-риск ветка исполнена
    leg0382_u = [t for t in tr_u if t.entry_fib == 0.382]
    ok_u = any(t.outcome == "target" and t.ret_pct < 0 for t in leg0382_u)
    # perleg: нога 0.382 НЕ должна закрываться по 0.5 в минус (целит в 0.236=115.28 → не достигнут)
    leg0382_p = [t for t in tr_p if t.entry_fib == 0.382]
    ok_p = not any(t.outcome == "target" and t.ret_pct < 0 for t in leg0382_p)
    # глубокая нога 0.618 у обоих закрывается по 0.5 в плюс
    leg0618_u = [t for t in tr_u if t.entry_fib == 0.618 and t.outcome == "target" and t.ret_pct > 0]
    print(f"  uniform: нога0.382 закрыта по де-риску в минус: {ok_u} "
          f"(сделок по 0.382: {len(leg0382_u)}); нога0.618 в плюс: {len(leg0618_u)>0}")
    print(f"  perleg : нога0.382 НЕ закрыта по 0.5 в минус: {ok_p} "
          f"(сделок по 0.382: {len(leg0382_p)})")
    return ok_u and ok_p and len(leg0618_u) > 0


VARIANTS = {
    "base":       dict(policy=pol_base,       cancel_on_new_high=False),
    "v1_live":    dict(policy=pol_live,       cancel_on_new_high=False),
    "v2_uniform": dict(policy=pol_v2_uniform, cancel_on_new_high=True),
    "v2_nocancel":dict(policy=pol_v2_uniform, cancel_on_new_high=False),
    "v2_perleg":  dict(policy=pol_v2_perleg,  cancel_on_new_high=True),
    "v2_alt0382": dict(policy=pol_v2_alt0382, cancel_on_new_high=True),
}

COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "VETUSDT",
         "SEIUSDT", "TIAUSDT", "JTOUSDT", "BONKUSDT"]


def main():
    import os
    data_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dfs = {}
    print("ГЕЙТ 1 — мой код в режиме базы == движок (посделочно):")
    ok_all = True
    for sym in COINS:
        path = os.path.join(data_dir, f"{sym}_4h_cex.csv")
        if not os.path.exists(path):
            print(f"  ⚠ нет {path}"); continue
        df = pf.load_csv(path); dfs[sym] = df
        ok = gate_baseline(df, sym)
        print(f"  {'✓' if ok else '✗'} {sym}: {len(df)} баров — {ok}")
        ok_all = ok_all and ok
    if not ok_all:
        print("\n✗ Гейт 1 не прошёл. Стоп."); sys.exit(1)

    print("\nГЕЙТ 2 — синтетика реально исполняет de-risk-ветку (0.618→0.5):")
    if not gate_derisk_branch():
        print("\n✗ Гейт 2 не прошёл (de-risk-ветка ведёт себя не как задумано). Стоп."); sys.exit(1)
    print("✓ Гейт 2 пройден: уровень de-risk и per-leg исполняются и различимы.\n")

    # Контроль: pol_deriskoff (всегда 0.236) == base
    for sym, df in dfs.items():
        for mw in (48, 72):
            a = [_tk(t) for t in run_strategy(df, mw, policy=pol_base)]
            b = [_tk(t) for t in run_strategy(df, mw, policy=pol_deriskoff)]
            if a != b:
                print(f"  ✗ контроль deriskoff != base {sym} mw={mw}"); sys.exit(1)
    print("✓ Контроль: политика «всегда 0.236» идентична базе (как и ожидалось).\n")

    for mw in (48, 72):
        print("=" * 80)
        print(f"СРАВНЕНИЕ — MAX_WAIT={mw}, агрегат по {len(dfs)} монетам "
              f"(вход общий: min_bar_pct={pf.MIN_BAR_PCT}, no_retrace={pf.IMPULSE_NO_RETRACE}, stop={pf.STOP_FIB})")
        print("=" * 80)
        hdr = f"{'вариант':<12}{'сделок':>8}{'winrate':>9}{'эксп/сд':>10}{'итог%(ранж)':>13}{'макс.DD*':>10}{'PF':>7}{'t*':>7}"
        print(hdr); print("-" * len(hdr))
        for vname, kw in VARIANTS.items():
            all_tr = []
            for sym, df in dfs.items():
                all_tr += run_strategy(df, mw, **kw)
            m = pf.metrics(all_tr, vname)
            print(f"{vname:<12}{m['n']:>8}{m['winrate_%']:>8}%{m['expectancy_%_per_trade']:>10}"
                  f"{m['total_return_%']:>13}{m['max_drawdown_%']:>10}{str(m['profit_factor']):>7}{m['t_stat']:>7}")
        print()

    print("=" * 80)
    print("ПО МОНЕТАМ (MAX_WAIT=48): эксп.%/сделку (число сделок)")
    print("=" * 80)
    hdr = f"{'монета':<10}" + "".join(f"{v:>13}" for v in VARIANTS)
    print(hdr); print("-" * len(hdr))
    for sym, df in dfs.items():
        cells = []
        for vname, kw in VARIANTS.items():
            m = pf.metrics(run_strategy(df, 48, **kw), vname)
            cells.append(f"{m.get('expectancy_%_per_trade',0)}({m.get('n',0)})")
        print(f"{sym:<10}" + "".join(f"{c:>13}" for c in cells))
    print("\n* maxDD и t — артефакты склейки монат по порядку, НЕ портфельные метрики.")
    print("* итог% — сумма %/сделку без компаундинга, равный вес ноги; метрика РАНЖИРОВАНИЯ, не P&L счёта.")


if __name__ == "__main__":
    main()
