# -*- coding: utf-8 -*-
"""Путь к котировкам для движка-эталона — де-хардкод абсолютного `DD`.

`DATA_DIR` берётся из окружения (env `DATA_DIR`), дефолт `repo_root/data`.
Движок самодостаточен (НЕ импортирует пакет `config`, чтобы эталон не зависел от обвязки),
но контракт env ЕДИНЫЙ с `config.ops.DATA_DIR` — та же переменная `DATA_DIR`, тот же дефолт,
иначе движок и live-обвязка разойдутся по данным (нарушение parity).
"""
import os

# __file__ = <repo>/strategy/engine/_paths.py → три уровня вверх = корень репозитория.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(_ROOT, "data")
