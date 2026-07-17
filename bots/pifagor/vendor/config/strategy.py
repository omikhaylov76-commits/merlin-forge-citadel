# -*- coding: utf-8 -*-
"""Крутилки слоя сигнала V8.1 (docs/04 §1–2, docs/01). Без секретов."""
import json
import os
import re

from ._env import ENV_ERRORS, env_bool

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
# ЭТАЛОННЫЙ дефолт (ADR-0019): при не заданном разъёме COINS_CONFIG == этот словарь БАЙТ-В-БАЙТ.
_DEFAULT_COINS_CONFIG = {
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

# ── Разъём внешней вселенной монет (ADR-0019, S8 «Динамо-близнец», Путь Б) ────────────
# Санкционированная дельта ЖИВОГО генома относительно замороженного архива b75bd17
# (единственная; реестр дельт — ADR-0019). Зачем: список монот не должен быть прибит
# гвоздями к коду — бот-«динамик» (Борс) берёт вселенную из разведки. Дефолт (env не задан /
# файла нет) = словарь выше БАЙТ-В-БАЙТ → Персиваль/Галахад/paper разъёма не замечают.
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}USDT$")   # только валидные тикеры USDT-перпетуала


def _num(sym, cfg, key, cast, default):
    """Число из внешнего JSON с приведением типа. Отсутствует → default. НЕ приводится (строка/bool/
    мусор) → ENV_ERRORS + default: строку в config.validate НЕ пускаем — там `val <= 0` на строке
    бросил бы TypeError сырым трейсбеком вместо понятного отказа (fail-loud)."""
    v = cfg.get(key)
    if v is None:
        return default
    if isinstance(v, bool):                                   # bool — подтип int, но не наш параметр
        ENV_ERRORS.append(f"COINS_CONFIG_PATH: {sym}.{key}={v!r} — не число")
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        ENV_ERRORS.append(f"COINS_CONFIG_PATH: {sym}.{key}={v!r} — не число")
        return default


def _coerce_coins(raw, path):
    """Структура/типы/нормализация внешнего JSON. Числовые параметры ПРИВОДИМ к типу (строка/мусор →
    None+лог, не сырой краш в validate); диапазоны (mb1/mb2>0, leverage 1..5, weight>0) проверяет
    config.validate(). Мусорный символ пропускаем+логируем. Ключи присутствуют всегда (main.py:234
    берёт leverage прямым subscript). weight всегда число (validate суммирует веса pool). Верхний
    регистр как ключ dict = де-дуп (последний выигрывает)."""
    if not isinstance(raw, dict):
        ENV_ERRORS.append(f"COINS_CONFIG_PATH={path!r} — ожидался объект {{символ: {{...}}}}")
        return None
    out = {}
    for sym, cfg in raw.items():
        s = str(sym).strip().upper()
        if not _SYMBOL_RE.match(s):
            ENV_ERRORS.append(f"COINS_CONFIG_PATH: символ {sym!r} не тикер …USDT — пропуск")
            continue
        if not isinstance(cfg, dict):
            ENV_ERRORS.append(f"COINS_CONFIG_PATH: {s} — параметры не объект — пропуск")
            continue
        out[s] = {
            "enabled": bool(cfg.get("enabled", False)),
            "mb1": _num(s, cfg, "mb1", float, None),          # None → validate: «не положителен»
            "mb2": _num(s, cfg, "mb2", float, None),
            "leverage": _num(s, cfg, "leverage", int, None),
            "weight": _num(s, cfg, "weight", float, 1.0),     # вес всегда число (validate суммирует)
        }
    if not out:
        ENV_ERRORS.append(f"COINS_CONFIG_PATH={path!r} — валидных монет не осталось")
        return None
    return out


def _load_coins_config():
    """COINS_CONFIG из внешнего JSON-файла (пишет провайдер картриджа атомарно), если задан env
    COINS_CONFIG_PATH и файл существует; иначе — _DEFAULT_COINS_CONFIG (тот же объект, байт-в-байт).
    REPLACE: внешний файл заменяет вселенную ЦЕЛИКОМ (не merge). Кривой вход НЕ роняет процесс сырым
    трейсбеком — проблема в ENV_ERRORS, config.validate() выведет и остановит старт (дисциплина
    «падать понятно», как env_int/env_float). Файл-путь, а НЕ инлайн-JSON в env: никакого shell-source
    недоверенного текста (страж инъекции, урок ADR-0018). Секретов канал не несёт (только монеты)."""
    path = os.environ.get("COINS_CONFIG_PATH")
    if not path or not path.strip():
        return _DEFAULT_COINS_CONFIG                 # разъём не задан → дефолт (Персиваль/Галахад/paper)
    path = path.strip()
    if not os.path.isfile(path):
        return _DEFAULT_COINS_CONFIG                 # файла ещё нет (холодный старт до провайдера) → дефолт
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        ENV_ERRORS.append(f"COINS_CONFIG_PATH={path!r} — не читается/не JSON: {exc}")
        return _DEFAULT_COINS_CONFIG
    coins = _coerce_coins(raw, path)
    return coins if coins is not None else _DEFAULT_COINS_CONFIG


COINS_CONFIG = _load_coins_config()
