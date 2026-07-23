# -*- coding: utf-8 -*-
"""config.knobs — реестр рантайм-крутилок Пифагор V8.1 (Веха 4 фича 2).

ЕДИНЫЙ источник метаданных каждой 🎛-крутилки: тип, диапазон/enum, дефолт (из config-подмодулей).
Используется ConfigStore для валидации записи (set) и типизации чтения (config_state хранит TEXT),
а также config.validate() (DRY, под-шаг 3) для старт-проверки. Диапазоны — зеркало config.validate
(docs/04, docs/02). Кросс-кноб инвариант (0<ALARM_DD<KILLSWITCH_DD<1) — функция `cross_check` (ЕДИНЫЙ
источник: config.validate на старте + ConfigStore на записи set и чтении effective). Чистый модуль: без БД/IO.
"""
import math

from . import risk, capital, execution, strategy, ops

# t: "num" | "enum" | "bool"; для num — py (float/int), lo/hi (None=без границы), lo_inc/hi_inc (вкл/искл).
KNOB_SPECS = {
    "RISK_PCT_PER_LEG": {"t": "num", "py": float, "lo": 0.5, "hi": 10.0},
    "RISK_PCT_ALARM":   {"t": "num", "py": float, "lo": 0.0, "hi": 10.0, "lo_inc": False},
    "KILLSWITCH_DD":    {"t": "num", "py": float, "lo": 0.0, "hi": 1.0, "lo_inc": False, "hi_inc": False},
    "ALARM_DD":         {"t": "num", "py": float, "lo": 0.0, "hi": 1.0, "lo_inc": False, "hi_inc": False},
    "CONCURRENCY_CAP":  {"t": "num", "py": int, "lo": 1, "hi": 24},   # ADR-0023: потолок 24 (динамик-характер Борса, демо) — вне боевого OOS-конверта эталона; паспорт правдив только внутри 16, до реальных денег ре-бэктест ИЛИ явная пометка витрины
    "MAX_LEVERAGE":     {"t": "num", "py": int, "lo": 1, "hi": 5},   # parity-cap: движок жёстко min(5.0,…) (port_lib.py:128); >5 = вне честных OOS-чисел → отдельный ADR + ре-бэктест
    "REFINANCE_SPLIT":  {"t": "num", "py": float, "lo": 0.0, "hi": 1.0, "lo_inc": False, "hi_inc": False},
    "WORKING_START":    {"t": "num", "py": float, "lo": 0.0, "lo_inc": False},
    "CUSHION_START":    {"t": "num", "py": float, "lo": 0.0},
    "STOP_FIB":         {"t": "num", "py": float, "lo": 0.5, "hi": 1.5},
    "SL_TRIGGER_BY":    {"t": "enum", "py": str, "values": ("LastPrice", "MarkPrice", "IndexPrice")},
    "SHORTS_ENABLED":   {"t": "bool", "py": bool},
    "EMA_FILTER_ENABLED": {"t": "bool", "py": bool},
    "REANCHOR_AFTER_SCALP": {"t": "bool", "py": bool},   # v3-режим: пере-якорь после закрытого скальпа 0.382 (demo-first)
    "PAUSE_ENABLED":    {"t": "bool", "py": bool},   # аварийная Пауза дашборда (ADR 0011); enforcement — Веха 5
    "WARM_ON_START":    {"t": "bool", "py": bool},   # авто-подхват живых сетапов на старте (ADR 0013); авто = auto_eligible PENDING
    "WARM_MAX_AGE_BARS": {"t": "num", "py": int, "lo": 1, "hi": 500},  # окно свежести пробоя (закрытые 4h; деф 72=TIMEOUT_BARS)
    "RUNNER_TP_HOLD":   {"t": "bool", "py": bool},   # фикс «живой бегунок» (ADR 0015): нога 0.5 без TP 0.236 до профита
    "LEG2_EXT":         {"t": "num", "py": float, "lo": 0.0, "hi": 3.0},   # цель бегунка ext(LEG2_EXT); ≠1.0 вне честных чисел
    "DOUBLE_DIP_ENABLED": {"t": "bool", "py": bool},   # двойной заход 4–5% (ADR 0016, 5.9): перезаход 0.5 с допуском после скальпа 0.382
    "DOUBLE_DIP_TOL":   {"t": "num", "py": float, "lo": 0.0, "hi": 0.10},   # % допуска высоты импульса |B−A|; ≠0.04 вне честных чисел
    "TRAIL_ENABLED":    {"t": "bool", "py": bool},   # R8-трейл бегунка (ADR 00XX, путь Y нативный трейлер Bybit, дизайн A); OFF=бит-в-бит
    "TRAIL_R":          {"t": "num", "py": float, "lo": 0.1, "hi": 3.0},   # ширина трейла R=TRAIL_R·(B−A); ≠дефолт 0.4 вне честных чисел (форвард)
}

KNOBS = tuple(KNOB_SPECS)

# Откуда брать дефолт (значение env/config, если в config_state нет override). (модуль, имя атрибута).
_DEFAULT_SRC = {
    "RISK_PCT_PER_LEG": (risk, "RISK_PCT_PER_LEG"),
    "RISK_PCT_ALARM":   (risk, "RISK_PCT_ALARM"),
    "KILLSWITCH_DD":    (risk, "KILLSWITCH_DD"),
    "ALARM_DD":         (risk, "ALARM_DD"),
    "CONCURRENCY_CAP":  (risk, "CONCURRENCY_CAP"),
    "MAX_LEVERAGE":     (risk, "MAX_LEVERAGE"),
    "REFINANCE_SPLIT":  (capital, "REFINANCE_SPLIT"),
    "WORKING_START":    (capital, "WORKING_START"),
    "CUSHION_START":    (capital, "CUSHION_START"),
    "STOP_FIB":         (execution, "STOP_FIB"),
    "SL_TRIGGER_BY":    (execution, "SL_TRIGGER_BY"),
    "SHORTS_ENABLED":   (strategy, "SHORTS_ENABLED"),
    "EMA_FILTER_ENABLED": (strategy, "EMA_FILTER_ENABLED"),
    "REANCHOR_AFTER_SCALP": (execution, "REANCHOR_AFTER_SCALP"),
    "PAUSE_ENABLED":    (ops, "PAUSE_ENABLED"),
    "WARM_ON_START":    (ops, "WARM_ON_START"),
    "WARM_MAX_AGE_BARS": (ops, "WARM_MAX_AGE_BARS"),
    "RUNNER_TP_HOLD":   (execution, "RUNNER_TP_HOLD"),
    "LEG2_EXT":         (execution, "LEG2_EXT"),
    "DOUBLE_DIP_ENABLED": (execution, "DOUBLE_DIP_ENABLED"),
    "DOUBLE_DIP_TOL":   (execution, "DOUBLE_DIP_TOL"),
    "TRAIL_ENABLED":    (execution, "TRAIL_ENABLED"),
    "TRAIL_R":          (execution, "TRAIL_R"),
}


def coerce(key, value):
    """Привести value (str из config_state ИЛИ типизированное) к типу крутилки. Бросает ValueError на
    мусоре. KeyError, если key неизвестен (вызывающий проверяет членство — см. validate)."""
    spec = KNOB_SPECS[key]
    t = spec["t"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value in (0, 1):                            # только 0/1 как булево; 2/1.5 -> ошибка
                return bool(value)
            raise ValueError(f"{key}: не булево значение {value!r}")
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key}: не булево значение {value!r}")
    if t == "enum":
        return str(value)
    # num
    try:
        f = float(value)                               # ValueError на нечисле; TypeError на None/list/dict
    except (ValueError, TypeError):
        raise ValueError(f"{key}: ожидается число, дано {value!r}")
    if not math.isfinite(f):                           # отсечь NaN/inf (иначе сравнения в validate -> False -> ложный OK)
        raise ValueError(f"{key}: не конечное число {value!r}")
    if spec["py"] is int:
        if f != int(f):
            raise ValueError(f"{key}: ожидается целое, дано {value!r}")
        return int(f)
    return f


def parse(key, text):
    """config_state хранит TEXT -> типизированное значение (то же, что coerce)."""
    return coerce(key, text)


def validate(key, value):
    """(ok, err): известна ли крутилка, приводится ли к типу, в диапазоне/enum ли. Кросс-кноб
    инварианты — НЕ здесь (нужен эффективный конфиг, см. ConfigStore._cross_check)."""
    if key not in KNOB_SPECS:
        return False, f"неизвестная крутилка: {key}"
    try:
        val = coerce(key, value)
    except (ValueError, TypeError) as e:
        return False, str(e)
    spec = KNOB_SPECS[key]
    t = spec["t"]
    if t == "enum":
        if val not in spec["values"]:
            return False, f"{key}={val!r} ∉ {spec['values']}"
        return True, None
    if t == "bool":
        return True, None
    lo, hi = spec.get("lo"), spec.get("hi")
    lo_inc, hi_inc = spec.get("lo_inc", True), spec.get("hi_inc", True)
    if lo is not None and (val < lo or (val == lo and not lo_inc)):
        return False, f"{key}={val} нарушает нижнюю границу ({'≥' if lo_inc else '>'} {lo})"
    if hi is not None and (val > hi or (val == hi and not hi_inc)):
        return False, f"{key}={val} нарушает верхнюю границу ({'≤' if hi_inc else '<'} {hi})"
    return True, None


def default(key):
    """Дефолтное значение крутилки из config-подмодуля (env/код), если в config_state нет override."""
    mod, attr = _DEFAULT_SRC[key]
    return getattr(mod, attr)


def cross_check(values):
    """Кросс-кноб инвариант ПОРЯДКА порогов: 0 < ALARM_DD < KILLSWITCH_DD < 1 (доли в (0,1) валидирует
    validate пер-кноб; тут — взаимный порядок, нужен эффективный конфиг сразу обеих крутилок). ЕДИНЫЙ
    источник: config.validate (старт), ConfigStore (запись set + чтение effective). (ok, err|None).
    Неполный набор (нет какой-то DD) -> True (отсутствие ловит validate). RISK_PCT_ALARM ≤ RISK_PCT_PER_LEG
    здесь НЕ форсится — выбор владельца (docs/04, soft-warn вызывающего, не инвариант)."""
    a, k = values.get("ALARM_DD"), values.get("KILLSWITCH_DD")
    if a is None or k is None:
        return True, None
    if not (0 < a < k < 1):
        return False, f"нужно 0 < ALARM_DD({a}) < KILLSWITCH_DD({k}) < 1"
    return True, None
