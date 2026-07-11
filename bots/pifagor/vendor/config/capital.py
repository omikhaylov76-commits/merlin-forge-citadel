# -*- coding: utf-8 -*-
"""Крутилки капитала V8.1 (docs/04 §4, docs/02 §3–4, ADR 0003)."""
import os

from ._env import env_float, env_str

# pool (рекомендуется): общий working-пул, риск % от total working, cap ограничивает суммарную
# экспозицию, вклад монеты = weight. per_coin: каждая монета — свой deposit_usd, без портфельного эффекта.
CAPITAL_MODE = env_str("CAPITAL_MODE", "pool")

WORKING_START = env_float("WORKING_START", 10000)  # рабочий капитал на старте (pool)
CUSHION_START = env_float("CUSHION_START", 10000)  # подушка на старте (~1:1 с working)

# per_coin режим: депозит на монету (если не задан per-coin в COINS_CONFIG). None, если не указан.
DEPOSIT_PER_COIN = None
if os.environ.get("DEPOSIT_PER_COIN", "").strip():
    DEPOSIT_PER_COIN = env_float("DEPOSIT_PER_COIN", 0.0)

# Месячный рефинанс прибыли 50/50 в подушку (структура само-делевереджится).
REFINANCE_SPLIT = env_float("REFINANCE_SPLIT", 0.5)
REFINANCE_PERIOD = env_str("REFINANCE_PERIOD", "monthly")
