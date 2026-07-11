# -*- coding: utf-8 -*-
"""Крутилки риска V8.1 (docs/04 §4, docs/02). Часть — рантайм-переопределяема с дашборда."""
from ._env import env_float, env_int

# Главная дашборд-переменная: риск на ногу, % от working-капитала. Дефолт 1.3, диапазон 0.5–10.
RISK_PCT_PER_LEG = env_float("RISK_PCT_PER_LEG", 1.3)

# Риск после тревоги −40% (риск вдвое).
RISK_PCT_ALARM = env_float("RISK_PCT_ALARM", 0.65)

# Ограничитель экспозиции: макс одновременных ЗАЛИТЫХ ног (не плечо).
CONCURRENCY_CAP = env_int("CONCURRENCY_CAP", 8)

# Плечо как потолок (per-coin может переопределять).
MAX_LEVERAGE = env_int("MAX_LEVERAGE", 5)

# Просадочные пороги на общий live-капитал (15m-контур): kill-switch / тревога.
KILLSWITCH_DD = env_float("KILLSWITCH_DD", 0.50)
ALARM_DD = env_float("ALARM_DD", 0.40)
