#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config — единый источник правды по крутилкам Пифагор V8.1.

Загружает .env (если есть), собирает настройки из окружения в подмодулях
strategy / risk / capital / execution / ops и предоставляет validate(),
который ПОНЯТНО падает без ключей, при кривом типе env или при выходе knob
за допустимый диапазон.

Все секреты — только из переменных окружения (.env локально / Railway env vars),
НИКОГДА не в коде. Дашборд импортирует config для чтения значений, но validate()
не зовёт (ему ключи не нужны — это keyless-граница безопасности).
"""
import os


def _load_env():
    """Подхватить корневой .env (k=v построчно) через setdefault — реальные env-vars
    окружения (Railway) имеют приоритет над .env. Снимаем `export`, обрамляющие
    кавычки и инлайн-комментарии (типовые ловушки .env)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]  # снять обрамляющие кавычки
            else:
                idx = val.find(" #")  # инлайн-комментарий (только для некавыченных)
                if idx != -1:
                    val = val[:idx].strip()
            if key:
                os.environ.setdefault(key, val)


_load_env()

# Импортируем подмодули ПОСЛЕ загрузки .env — они читают os.environ на импорте.
from . import _env, strategy, risk, capital, execution, ops  # noqa: E402
from . import knobs  # noqa: E402  (реестр крутилок; импортит risk/capital/execution/strategy — уже загружены)


def validate():
    """Проверить полноту/корректность конфига. Возвращает True или бросает SystemExit
    с человекочитаемым перечнем проблем. Зовётся первой в точке входа worker."""
    # Ошибки разбора env (кривой тип числа/булева) — собраны при импорте подмодулей.
    problems = list(_env.ENV_ERRORS)

    # 1. Секреты (главное условие приёмки Вехи 1 — падать понятно без ключей)
    missing = []
    if not ops.BYBIT_API_KEY:
        missing.append("BYBIT_API_KEY")
    if not ops.BYBIT_API_SECRET:
        missing.append("BYBIT_API_SECRET")
    if missing:
        problems.append("не заданы переменные окружения: " + ", ".join(missing))

    # 1.5 ПРЕДОХРАНИТЕЛЬ MAINNET (5.5b): боевой счёт (BYBIT_DEMO=0) ТОЛЬКО с явным ALLOW_MAINNET=1 — чтобы
    # забытая/перепутанная переменная не увела бота на реальные деньги. Demo (дефолт) свободен (LIVE на
    # mainnet тоже невозможен без этого флага). Снимать предохранитель — осознанно, в Вехе 6 (go-live).
    if not ops.USE_DEMO and not ops.ALLOW_MAINNET:
        problems.append("MAINNET (BYBIT_DEMO=0) запрещён без явного ALLOW_MAINNET=1 — предохранитель от "
                        "случайного боевого запуска (для demo-форварда оставь BYBIT_DEMO=1)")

    # 2. Рантайм-крутилки — единый реестр config.knobs (диапазоны/enum в ОДНОМ источнике с ConfigStore,
    # без дрейфа). Кросс-кноб (нужны обе крутилки) и режимные/per-coin — инлайн ниже.
    for key in ("RISK_PCT_PER_LEG", "RISK_PCT_ALARM", "CONCURRENCY_CAP", "MAX_LEVERAGE",
                "REFINANCE_SPLIT", "STOP_FIB", "LEG2_EXT", "DOUBLE_DIP_TOL", "SL_TRIGGER_BY", "WARM_MAX_AGE_BARS"):
        ok, err = knobs.validate(key, knobs.default(key))
        if not ok:
            problems.append(err)
    ok, err = knobs.cross_check({"ALARM_DD": risk.ALARM_DD, "KILLSWITCH_DD": risk.KILLSWITCH_DD})
    if not ok:                                          # ЕДИНЫЙ источник DD-инварианта (DRY с ConfigStore)
        problems.append(err)

    # 3. Капитал (REFINANCE_SPLIT — в реестре выше; режимные/стартовые — здесь)
    if capital.CAPITAL_MODE not in ("pool", "per_coin"):
        problems.append(f"CAPITAL_MODE={capital.CAPITAL_MODE} ∉ {{pool, per_coin}}")

    # 4. Монеты
    enabled = [(s, c) for s, c in strategy.COINS_CONFIG.items() if c.get("enabled")]
    if not enabled:
        problems.append("нет ни одной включённой монеты (enabled=True)")
    for sym, cfg in enabled:
        for key in ("mb1", "mb2", "leverage"):
            val = cfg.get(key)
            if val is None or val <= 0:
                problems.append(f"{sym}: {key} не задан или не положителен")
        lev = cfg.get("leverage")
        if lev is not None and not (1 <= lev <= 5):
            problems.append(f"{sym}: leverage={lev} вне диапазона 1–5 (parity-cap движка 5.0)")

    if capital.CAPITAL_MODE == "pool":
        if capital.WORKING_START <= 0:
            problems.append("WORKING_START должен быть > 0 (режим pool)")
        if capital.CUSHION_START < 0:
            problems.append("CUSHION_START должен быть ≥ 0 (режим pool)")
        if enabled and sum(c.get("weight", 0) for _, c in enabled) <= 0:
            problems.append("сумма весов включённых монет должна быть > 0 (режим pool)")
    elif capital.CAPITAL_MODE == "per_coin":
        for sym, cfg in enabled:
            dep = cfg.get("deposit_usd")
            if not dep or dep <= 0:
                problems.append(f"{sym}: deposit_usd обязателен и > 0 в режиме per_coin")

    # 5. Исполнение / эксплуатация
    if execution.TIMEOUT_BARS < 1:
        problems.append("TIMEOUT_BARS должен быть ≥ 1 (закрытые 4h-бары)")
    if ops.EXEC_POLL_SEC <= 0:
        problems.append("EXEC_POLL_SEC должен быть > 0")
    if ops.HEARTBEAT_SEC <= 0:
        problems.append("HEARTBEAT_SEC должен быть > 0")
    # 15m-планировщик: интервал — только МИНУТНЫЕ Bybit-интервалы (D/W/M сломали бы
    # выравнивание next_boundary_ms); период цикла — один источник правды (EXEC_INTERVAL).
    minute_intervals = ("1", "3", "5", "15", "30", "60", "120", "240", "360", "720")
    if ops.EXEC_INTERVAL not in minute_intervals:
        problems.append(
            f"EXEC_INTERVAL={ops.EXEC_INTERVAL!r} ∉ минутных интервалов Bybit "
            f"{minute_intervals} (парити-дефолт '15')"
        )
    elif ops.EXEC_POLL_SEC != int(ops.EXEC_INTERVAL) * 60:
        problems.append(
            f"EXEC_POLL_SEC={ops.EXEC_POLL_SEC} должен совпадать с EXEC_INTERVAL "
            f"({ops.EXEC_INTERVAL}m = {int(ops.EXEC_INTERVAL) * 60}s) — один источник правды по периоду"
        )
    if not (2 <= ops.EXEC_KLINE_LIMIT <= 1000):
        problems.append(f"EXEC_KLINE_LIMIT={ops.EXEC_KLINE_LIMIT} вне диапазона 2–1000 (лимит Bybit)")
    # STOP_FIB / SL_TRIGGER_BY — в реестре config.knobs (секция 2).

    if problems:
        raise SystemExit(
            "config.validate() — конфиг неполон или некорректен:\n  - "
            + "\n  - ".join(problems)
            + "\n\nЗадай переменные в .env (локально) или в Railway env vars. "
            "См. .env.example и README."
        )
    return True
