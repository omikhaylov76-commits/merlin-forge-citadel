# -*- coding: utf-8 -*-
"""scout.scan — Этап B: ЖИВОЕ ведение последнего сетапа по логике движка (Веха 7, Path A).

Читает окно свечей из КЭША (scout_klines, под-шаг 2b), ведёт последний живой сетап монеты пре-commit циклом
движка (`_track_setup`) и классифицирует СЕЙЧАС:
  🔥 forming   — толчок-1 + консолидация, пробоя ещё нет (forming_candidate);
  📈 tracking  — импульс родился, цена НАД входом → вершина едет за ценой (пере-якорь), отката к входу нет;
  ✅ ready     — цена в зоне входа (0.382, не дошла до 0.5) → можно брать.
Откат к 0.5 (commit) → сетап ОТРАБОТАЛ → снят, ждём НОВЫЙ импульс. Паритет: детекция/геометрия — ДВИЖОК
(scan_signal + signal_from_detect), логика ведения — зеркало run_v8 pre-commit на 4h (заливы по low/high бара,
не 15m — конвенция скаута). scan_signal зовём с явными mb1/mb2 + ema_off/shorts_off. Это СТРУКТУРА, НЕ прибыль.
"""
import json

import numpy as np

import config
import scout.config as scfg
from scout import klines_cache as kcache
from scout.public_api import RateLimitBan
from strategy.candidates import forming_candidate
from strategy.scanner import scan_signal
from strategy.signal import signal_from_detect

_ENTRY_HI = 0.382       # верхний вход (первый откат от B); «нетронут» = цена его ещё не достигла


def _track_setup(o, h, l, c, jc, A, Bbirth, *, stop_fib, reanchor_after_scalp=True):
    """Пре-commit жизненный цикл сетапа на 4h-барах — зеркало ЛОГИКИ run_v8 pre-commit (v8_sim.py:129-183),
    заливы по low/high 4h-бара (у скаута нет 15m в Фазе 1). Тянет вершину за ценой (пере-якорь на новых хаях),
    ловит commit при откате к 0.5, ретайрит. reanchor_after_scalp=True — v3 (demo): перезаряжает закрытую
    скальп-ногу на новом хае. Возврат {state:'live'|'committed'|'dead', A, B(текущая), anchor_bar, resolve_bar}."""
    n = len(c); A = float(A); B = float(Bbirth); anchor_bar = int(jc); state382 = "pending"
    k = jc + 1
    while k < n:
        span = B - A
        e382 = B - span * 0.382; e05 = B - span * 0.5
        e236 = B - span * 0.236; stop = B - span * float(stop_fib)
        lk = float(l[k]); hk = float(h[k])
        filled_this = False
        # FILL first (движок): откат к 0.5 → commit; иначе откат к 0.382 → open
        if lk <= e05 + 1e-12:
            return {"state": "committed", "A": A, "B": B, "anchor_bar": anchor_bar, "resolve_bar": int(k)}
        if state382 == "pending" and lk <= e382 + 1e-12:
            state382 = "open"; filled_this = True
        # RE-ANCHOR: не залито этим баром, 0.382 не open, новый хай → вершина едет за ценой
        if not filled_this and state382 != "open":
            has_closed = (state382 == "closed")
            if ((not has_closed) or reanchor_after_scalp) and hk > B + 1e-12:
                B = hk; anchor_bar = int(k); state382 = "pending"
                k += 1; continue
        # SCALP 0.382 (open, hk≥0.236) → закрыта (v3 ре-армит на новом хае)
        if state382 == "open" and hk >= e236 - 1e-12:
            state382 = "closed"
        # STOP пре-commit (обычно недостижим: 0.5 выше стопа → commit срабатывает раньше)
        if lk <= stop + 1e-12:
            return {"state": "dead", "A": A, "B": B, "anchor_bar": anchor_bar, "resolve_bar": int(k)}
        k += 1
    return {"state": "live", "A": A, "B": B, "anchor_bar": anchor_bar, "resolve_bar": None}


def classify(o, h, l, c, t4, symbol, mb1, mb2, *, fresh_bars, stop_fib=None):
    """Статус монеты СЕЙЧАС (Path A — ЖИВОЕ ведение последнего сетапа по логике движка). Ведёт каждый импульс
    пре-commit циклом: тянется (нет отката к входу) → готов (в зоне 0.382) → откат к 0.5 = отработал (ретайр,
    ждём НОВЫЙ импульс). None — не кандидат. o/h/l/c — np-массивы закрытой серии."""
    n = len(c)
    if n < 3:
        return None
    price = float(c[-1])
    if price <= 0:
        return None
    sfib = stop_fib if stop_fib is not None else config.execution.STOP_FIB

    # ── найти ПОСЛЕДНИЙ ЖИВОЙ сетап: вести каждый импульс; committed/dead → искать следующий ПОСЛЕ него ──
    live = None; i = 2; guard = 0
    while i < n - 1 and guard < n + 2:
        guard += 1
        r = scan_signal(o, h, l, c, t4, symbol, start_i=i,
                        ema_enabled=False, shorts_enabled=False, mb1=mb1, mb2=mb2)
        if r is None:
            break
        _card0, jc, _nxt = r
        res = _track_setup(o, h, l, c, jc, _card0["A"], _card0["B"], stop_fib=sfib)
        if res["state"] == "live":
            live = (int(jc), res); break        # живой тянется до конца данных → он последний (как движок)
        i = max(int(res["resolve_bar"] or jc) + 1, int(jc) + 1)   # committed/dead → следующий импульс

    if live is not None and live[0] >= n - fresh_bars:
        jc, res = live
        A, B, ja = res["A"], res["B"], int(res["anchor_bar"])
        card = signal_from_detect("long", A, B, jc, t4=t4, stop_fib=sfib)
        entry_hi = card["entries"][_ENTRY_HI]; stop = card["stop"]
        lows_since_anchor = l[ja + 1:n]
        touched = lows_since_anchor.size > 0 and float(np.min(lows_since_anchor)) <= entry_hi
        status = "ready" if touched else "tracking"
        return {
            "symbol": symbol, "status": status,
            "jc": int(jc), "anchor_bar": ja, "A": A, "B": B,
            "entries": card["entries"], "stop": stop, "stop_fib": card["stop_fib"],
            "targets": card["targets"], "price": price,
            "dist_to_entry_pct": round((price - entry_hi) / price * 100.0, 3),
            "dist_to_stop_pct": round((price - stop) / price * 100.0, 3),
            "bars_since_anchor": int(n - 1 - ja),
            "note": ("готов — цена в зоне входа (0.382), сетка живая" if status == "ready"
                     else "тянется — цена над входом, вершина едет за ценой (пере-якорь); отката к входу ещё нет"),
        }

    # ── греется: толчок-1 + консолидация без пробоя (или все сетапы отработали → ждём новый импульс) ──
    fc = forming_candidate(o, h, l, c, mb1=mb1,
                           retr=config.strategy.RETR, clean_thr=config.strategy.CLEAN_THR, start_i=2)
    if fc is not None:
        return {
            "symbol": symbol, "status": "forming",
            "bar1_index": int(fc["bar1_index"]), "consolidation_bars": int(fc["consolidation_bars"]),
            "breakout_level": fc["breakout_level"], "breakout_dist_pct": round(fc["breakout_dist_pct"], 3),
            "cancel_level": fc["cancel_level"], "cancel_dist_pct": round(fc["cancel_dist_pct"], 3),
            "price": price,
            "note": "греется — пробой ещё не случился (нужен сильный+чистый толчок-2)",
        }
    return None


def _bars_for_tf(row, tf):
    """(mb1, mb2, bar_source) для ТФ из payload.bars_by_tf[tf] (под-шаг 7). Фолбэк на скалярные колонки
    scout_list — ТОЛЬКО для primary (SCOUT_TF): они всегда откалиброваны под 4h (curate_list зовёт bars_for
    без tf) → обратная совместимость со строками до 7a. Нет баров ТФ → (None, None, None) → монету пропускаем."""
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = None
    bt = payload.get("bars_by_tf") if isinstance(payload, dict) else None
    b = bt.get(tf) if isinstance(bt, dict) else None
    if isinstance(b, dict) and b.get("mb1") is not None and b.get("mb2") is not None:
        return b.get("mb1"), b.get("mb2"), b.get("bar_source")
    if tf == scfg.SCOUT_TF:                     # фолбэк: primary-бары в скалярных колонках (строки до под-шага 7)
        return row.get("mb1"), row.get("mb2"), row.get("bar_source")
    return None, None, None


def scan_list(db, market, *, tf=None, now_ms=None, log=print):
    """Этап B: по каждой монете scout_list — докач кэша (2b) → classify → запись находок (snapshot per-ТФ +
    журнал). tf — какой ТФ сканируем; бары берём per-ТФ (под-шаг 7). RateLimitBan (403) пробрасываем."""
    tf = scfg.SCOUT_TF if tf is None else tf
    listed = db.scout_list_all()
    scan_bars = scfg.SCOUT_SCAN_BARS
    retention = max(scfg.SCOUT_SCAN_BARS, scfg.SCOUT_CAL_BARS)
    findings = []
    for row in listed:
        symbol = row["symbol"]
        mb1, mb2, src = _bars_for_tf(row, tf)
        if mb1 is None or mb2 is None:
            continue                           # нет баров этого ТФ у монеты (напр. 1h не откалиброван) → пропуск
        try:
            series = kcache.top_up(db, market, symbol, tf, scan_bars, retention=retention, now_ms=now_ms)
        except RateLimitBan:
            raise
        except Exception as e:                 # сбой одной монеты — не роняем весь скан
            log(f"  scan {symbol} FAIL: {e}")
            continue
        if not series or len(series) < 3:
            continue
        o = np.asarray([x["open"] for x in series], float)
        h = np.asarray([x["high"] for x in series], float)
        low = np.asarray([x["low"] for x in series], float)
        cl = np.asarray([x["close"] for x in series], float)
        t4 = np.asarray([x["time"] // 1000 for x in series], float)   # сек (bar_time), как find_signal
        f = classify(o, h, low, cl, t4, symbol, mb1, mb2, fresh_bars=scfg.SCOUT_FRESH_BARS)
        if f is not None:
            f["tf"] = tf
            f["score"] = row["score"]
            f["mb1"], f["mb2"], f["bar_source"] = mb1, mb2, src
            findings.append(f)
    db.scout_findings_put_snapshot(findings, now_ms, tf=tf)
    db.scout_findings_log_put_many(findings, now_ms)
    return findings
