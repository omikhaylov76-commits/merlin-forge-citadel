# -*- coding: utf-8 -*-
"""config._env — устойчивый разбор переменных окружения.

Числа/булевы парсятся на импорте подмодулей. Кривое значение НЕ роняет процесс
сырым трейсбеком (это сломало бы критерий «падать понятно»): хелпер кладёт
человекочитаемую проблему в ENV_ERRORS и возвращает дефолт, а config.validate()
выводит ENV_ERRORS в общем перечне проблем.
"""
import os

# Накопитель проблем разбора env (читается config.validate()).
ENV_ERRORS = []

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f", ""}


def env_str(name, default=""):
    return os.environ.get(name, default)


def env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        ENV_ERRORS.append(f"{name}={raw!r} — не число (ожидался float)")
        return float(default)


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        ENV_ERRORS.append(f"{name}={raw!r} — не целое (ожидался int)")
        return int(default)


def env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    ENV_ERRORS.append(
        f"{name}={raw!r} — не булево (ожидалось 1/0/true/false/yes/no/on/off)"
    )
    return default
