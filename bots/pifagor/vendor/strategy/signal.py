# -*- coding: utf-8 -*-
"""strategy.signal — слой сигнала V8.1 (Веха 3 фича 3).

find_signal — ТОНКАЯ обёртка над движком-эталоном (strategy/engine): зовёт detect_v81,
применяет only-long + EMA200-тренд-фильтр и собирает уровни через pf.fib_price. Детекция,
EMA и фибо НЕ переписываются (parity-закон): живой сигнал == бэктест.

Контракт (docs/06): find_signal(o, h, l, c, i, symbol, t4=None) -> dict | None.
Цены entries/stop — байт-в-байт движок (run_v8: v8_sim.py:113-114). targets — НАЧАЛЬНЫЕ
(авторитетные динамические выходы — машина lifecycle, фича 5); parity-claim только на entries/stop.

Чистый модуль: без I/O/сети/брокера/БД/ордеров/циклов по барам/расписания. Импорты —
только strategy.engine (эталон, read-only) + config + numpy/pandas.
"""
import numpy as np
import pandas as pd

import config
from strategy.engine.v81_sim import detect_v81
from strategy.engine import pifagor_fib_backtest_v2_clean as pf

# Фибо-уровни ног — ровно литерал движка (v8_sim.py:32), чтобы ключи совпали downstream.
LV = [0.382, 0.5, 0.618]


def warm_ema(c):
    """Тёплая EMA200 на ПЕРЕДАННОЙ серии (ewm span adjust=False) — формула движка (v8_sim.py:103,
    port_lib._ema:67). Предусловие parity: ПОЛНАЯ серия закрытых 4h. ОДИН источник: _ema_gate + live-сканер."""
    return pd.Series(c).ewm(span=config.strategy.EMA_PERIOD, adjust=False).mean().to_numpy()


def _ema_gate(c, jc, side):
    """EMA200-тренд-фильтр как в движке run_v8 (v8_sim.py:108-112): тёплая EMA, гейт на баре jc.
    True = пропустить сделку, False = отвергнуть. NaN EMA -> пропустить (как движок)."""
    ema = warm_ema(c)
    if np.isnan(ema[jc]):
        return True
    up = c[jc] > ema[jc]
    if (side == "long" and not up) or (side == "short" and up):
        return False
    return True


def signal_from_detect(side, A, B, jc, *, t4=None, stop_fib=None):
    """Карточка сетапа из ГОТОВОГО кортежа detect_v81 (side,A,B,jc) — БЕЗ повторного detect/EMA/side-фильтра
    (применены вызывающим). ЕДИНАЯ точка геометрии цен (entries/stop/targets через движок pf.fib_price):
    зовут и find_signal, и live-сканер (strategy/scanner) — чтобы геометрия не разъехалась.
    stop_fib — эффективный (None ⇒ дефолт config). targets — НАЧАЛЬНЫЕ (авторитетные дин. выходы — lifecycle)."""
    sfib = stop_fib if stop_fib is not None else config.execution.STOP_FIB
    lp = lambda level: float(pf.fib_price(A, B, level, side))    # цена уровня фибы (движок)
    ext = lambda m: float(pf.fib_price(A, B, -m, side))          # расширение за B (движок)
    return {
        "side": side,
        "A": float(A), "B": float(B), "jc": int(jc),
        "entries": {lv: lp(lv) for lv in LV},               # 3 ноги (parity-точные)
        "stop": lp(sfib),                                   # стоп fib stop_fib (дефолт 1.0 -> == A)
        "stop_fib": float(sfib),
        "targets": {
            0.382: lp(config.execution.NEXT_SCALP[0.382]),  # fib 0.236 (защ. скальп NEXT_SCALP)
            0.5: ext(config.execution.LEG2_EXT),            # ext(1.0) = 2.0R (бегунок ноги2)
            0.618: lp(0.382),                               # нога3 -> fib 0.382 (LEG3_MODE)
        },
        "bar_time": (int(t4[jc]) if t4 is not None else None),
    }


def find_signal(o, h, l, c, i, symbol, t4=None, *, ema_enabled=None, shorts_enabled=None, stop_fib=None):
    """Сигнал V8.1 на баре i по символу symbol (per-coin mb1/mb2). dict сетапа или None.

    Parity: детекцию/фибо/EMA считает ДВИЖОК (detect_v81 + pf.fib_price), мы не переписываем.
    t4 — опц. массив open-time (сек) для bar_time; нет -> bar_time=None.
    ema_enabled/shorts_enabled/stop_fib — эффективные крутилки от 5.2-цикла; None ⇒ дефолт config (parity).
    """
    cfg = config.strategy.COINS_CONFIG.get(symbol)
    if not cfg or not cfg.get("enabled"):
        return None  # неизвестная/выключенная монета — не торгуем (guard)

    # Детектор-эталон. retr/clean_thr/maxwin = config (= дефолты detect_v81, что зовёт _longdet) —
    # передаём явно, чтобы развязаться от дефолтов и не разъехаться с config.
    imp = detect_v81(
        o, h, l, c, i,
        cfg["mb1"], cfg["mb2"],
        retr=config.strategy.RETR,
        clean_thr=config.strategy.CLEAN_THR,
        maxwin=config.strategy.MAXWIN,
    )
    if imp is None:
        return None
    side, A, B, jc = imp

    # Эффективные крутилки: параметр (от 5.2-цикла) приоритетнее статики config; None ⇒ дефолт.
    # 'is not None' (НЕ 'or'): чтобы False/0.0 от владельца не подменялись дефолтом.
    shorts = shorts_enabled if shorts_enabled is not None else config.strategy.SHORTS_ENABLED
    ema = ema_enabled if ema_enabled is not None else config.strategy.EMA_FILTER_ENABLED
    sfib = stop_fib if stop_fib is not None else config.execution.STOP_FIB

    # only-long: drop short, если шорт не разблокирован (зеркало port_lib._longdet; ADR 0009).
    if side != "long" and not shorts:
        return None

    # EMA200-фильтр — рантайм-крутилка (дефолт ВЫКЛ, ADR 0009; честные числа — с EMA ON).
    if ema and not _ema_gate(c, jc, side):
        return None

    # ЕДИНАЯ геометрия цен — signal_from_detect (та же точка, что и live-сканер 3b → без дрейфа).
    return signal_from_detect(side, A, B, jc, t4=t4, stop_fib=sfib)
