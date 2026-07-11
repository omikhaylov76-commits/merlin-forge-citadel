# -*- coding: utf-8 -*-
"""Крутилки слоя сигнала V8.1 (docs/04 §1–2, docs/01). Без секретов."""
from ._env import env_bool

# Двойной таймфрейм
SIGNAL_TF = "4h"   # сигнал ищется на закрытии 4h
EXEC_TF = "15m"    # заливы/стопы/цели разрешаются на 15m суб-барах

# Детектор «два толчка через консолидацию» (detect_v81)
RETR = 0.5         # граница консолидации: бар держится выше l1 + RETR*(h1-l1)
CLEAN_THR = 0.5    # «чистый» бар: (h - c) < CLEAN_THR*(h - l)
MAXWIN = 0         # макс длина консолидации в барах (0 = без лимита)

# Тренд-фильтр EMA200
EMA_PERIOD = 200
EMA_WARM = True    # тёплая EMA (фикс причинности #5)

# Рантайм-knobs (ADR 0009) — переопределяемы с дашборда (закладка «Настройки»),
# без предохранителей, по решению владельца. Оба по умолчанию ВЫКЛ.
# Нераспознанное значение env не молчит как False, а копится в _env.ENV_ERRORS -> validate().
SHORTS_ENABLED = env_bool("SHORTS_ENABLED", False)          # разблокировка шорта
EMA_FILTER_ENABLED = env_bool("EMA_FILTER_ENABLED", False)  # фильтр EMA200 вкл/выкл

# only-long — производное от SHORTS_ENABLED (чтобы не разъехались на Вехе 3)
LONG_ONLY = not SHORTS_ENABLED

# Вселенная монет: 16 enabled (10 V8.1 + 6 v2-расширение, Research R1; OP выкл — аудит «чистый драг») + резерв (enabled=False).
# per-coin: enabled, mb1, mb2 (пороги силы баров, %), leverage, weight (вес в pool).
COINS_CONFIG = {
    # — 10 включённых (mb1/mb2 из docs/01 §1.4) —
    "BTCUSDT":  {"enabled": True, "mb1": 1.5, "mb2": 2.5, "leverage": 5, "weight": 1.0},
    "ETHUSDT":  {"enabled": True, "mb1": 1.5, "mb2": 2.5, "leverage": 5, "weight": 1.0},
    "BNBUSDT":  {"enabled": True, "mb1": 1.5, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "DOGEUSDT": {"enabled": True, "mb1": 2.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "XRPUSDT":  {"enabled": True, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "ADAUSDT":  {"enabled": True, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "SOLUSDT":  {"enabled": True, "mb1": 3.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "LINKUSDT": {"enabled": True, "mb1": 1.5, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "LTCUSDT":  {"enabled": True, "mb1": 2.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "ATOMUSDT": {"enabled": True, "mb1": 3.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    # — 7 расширение v2 (Research R1: качественные монеты, робаст-бары; EMA-off/2.5%/cap16 — env на деплое) —
    "TRXUSDT":  {"enabled": True, "mb1": 2.5, "mb2": 4.0, "leverage": 5, "weight": 1.0},
    "UNIUSDT":  {"enabled": True, "mb1": 2.0, "mb2": 3.0, "leverage": 5, "weight": 1.0},
    "NEARUSDT": {"enabled": True, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "AAVEUSDT": {"enabled": True, "mb1": 2.5, "mb2": 4.0, "leverage": 5, "weight": 1.0},
    "FILUSDT":  {"enabled": True, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "INJUSDT":  {"enabled": True, "mb1": 3.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "OPUSDT":   {"enabled": False, "mb1": 1.5, "mb2": 2.5, "leverage": 5, "weight": 1.0},  # аудит v2: чистый драг (standalone убыточен, ухудшает портфель) — выкл
    # — 9 зарезервированных (выключены; пороги — стартовые ориентиры) —
    "AVAXUSDT": {"enabled": False, "mb1": 2.5, "mb2": 4.0, "leverage": 5, "weight": 1.0},
    "DOTUSDT":  {"enabled": False, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "BCHUSDT":  {"enabled": False, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0},
    "XLMUSDT":  {"enabled": False, "mb1": 2.5, "mb2": 4.0, "leverage": 5, "weight": 1.0},
    "VETUSDT":  {"enabled": False, "mb1": 2.5, "mb2": 4.0, "leverage": 5, "weight": 1.0},
    "SEIUSDT":  {"enabled": False, "mb1": 3.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "TIAUSDT":  {"enabled": False, "mb1": 3.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "JTOUSDT":  {"enabled": False, "mb1": 3.0, "mb2": 5.0, "leverage": 5, "weight": 1.0},
    "BONKUSDT": {"enabled": False, "mb1": 3.5, "mb2": 6.0, "leverage": 5, "weight": 1.0},
}
