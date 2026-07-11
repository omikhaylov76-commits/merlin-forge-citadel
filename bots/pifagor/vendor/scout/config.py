# -*- coding: utf-8 -*-
"""scout.config — крутилки сервиса-скаута (Веха 7, Фаза 1).

env-only и НЕ в реестре KNOB_SPECS дашборда — чтобы не трогать боевой конфиг-контур (§J плана).
Секретов нет: скаут keyless (только публичные эндпоинты Bybit); единственная внешняя связь —
`DATABASE_URL` (общая Postgres) читается через config.ops. Публичные данные demo==mainnet → бьём
в mainnet-домен (как dashboard/prices.py).
"""
from config._env import env_bool, env_int, env_str

# ── что и как сканируем ──────────────────────────────────────────────────────
SCOUT_ENABLED = env_bool("SCOUT_ENABLED", True)
SCOUT_TF = env_str("SCOUT_TF", "4h")                       # сигнальный ТФ показа: '4h' | '1h' (под-шаг 7)
SCOUT_AUTO = env_bool("SCOUT_AUTO", True)                  # авто-скан на 4h/1h-границах (иначе только кнопка; под-шаг 4)
SCOUT_TFS = env_str("SCOUT_TFS", "4h,1h")                  # ТФ для калибровки баров + скана Этапа B (под-шаг 7); primary = SCOUT_TF
# 1h-трек (под-шаг 7). ДЕФОЛТ ON с 7b: вью-модель дашборда стала tf-aware (переключатель 4h|1h, находки
# ключуются по (symbol,tf)) → задвоения карточек больше нет. ⚠ ПОРЯДОК ДЕПЛОЯ: выкатывать дашборд (7b) НЕ
# позже скаута, иначе окно, где старый дашборд видит 1h-строки без tf-фильтра. Выключить 1h → env=0.
SCOUT_TF_1H_ENABLED = env_bool("SCOUT_TF_1H_ENABLED", True)

# ── размеры вселенной / списка (§C/§D плана) ─────────────────────────────────
SCOUT_UNIVERSE_MAX = env_int("SCOUT_UNIVERSE_MAX", 300)    # сколько топ-по-обороту монет тянуть klines (Этап A)
SCOUT_LIST_MAX = env_int("SCOUT_LIST_MAX", 200)            # размер курированного списка (ТОП-N по скору; под-шаг 2)
SCOUT_MIN_SCORE = env_int("SCOUT_MIN_SCORE", 35)           # пол скора «в список» (владелец 2026-07-08; под-шаг 2)

# ── окна истории ЧИСЛОМ (§F плана; EMA-off → 600-барный гейт не нужен) ────────
SCOUT_CAL_BARS = env_int("SCOUT_CAL_BARS", 1000)          # окно калибровки/состоятельности Этапа A (~166 дней 4h)
SCOUT_SCAN_BARS = env_int("SCOUT_SCAN_BARS", 300)         # окно скана сетапа Этапа B (под-шаг 3)
SCOUT_FRESH_BARS = env_int("SCOUT_FRESH_BARS", 72)        # окно свежести показа (под-шаг 3)

# ── пропускная способность (§H плана; per-IP 600/5с, 403+бан 10мин) ──────────
SCOUT_RPS = env_int("SCOUT_RPS", 3)                       # самоналоженный троттл публичного REST (3 = 2.5% квоты)
SCOUT_BASE_URL = env_str("SCOUT_BASE_URL", "https://api.bybit.com")   # публичный mainnet-домен
SCOUT_HTTP_TIMEOUT = env_int("SCOUT_HTTP_TIMEOUT", 10)

# ── расписание / сервис (под-шаг 4) ──────────────────────────────────────────
SCOUT_CAL_UTC_HOUR = env_int("SCOUT_CAL_UTC_HOUR", 5)      # утренний Этап A (05:00 UTC = 08:00 МСК)
SCOUT_POLL_SEC = env_int("SCOUT_POLL_SEC", 20)            # каденция wake-loop (проверка кнопки/границы)
SCOUT_BAN_SLEEP_SEC = env_int("SCOUT_BAN_SLEEP_SEC", 600)  # пауза при 403-бане IP (circuit-breaker §H)
SCOUT_LOCK_WAIT_SEC = env_int("SCOUT_LOCK_WAIT_SEC", 90)   # ждать освобождения advisory-лока при overlap-передеплое Railway (зеркало воркёрского 5.5c — НЕ крэшить)

# ── жёсткие отсевы состоятельности (§D плана) — дефолты из плана ──────────────
SCOUT_MIN_TURNOVER_USD = env_int("SCOUT_MIN_TURNOVER_USD", 5_000_000)
SCOUT_MIN_HISTORY_BARS = env_int("SCOUT_MIN_HISTORY_BARS", 300)
SCOUT_MIN_AGE_DAYS = env_int("SCOUT_MIN_AGE_DAYS", 180)
SCOUT_MAX_SPREAD_PCT = float(env_str("SCOUT_MAX_SPREAD_PCT", "0.15"))


# ── таймфреймы скана (под-шаг 7) ─────────────────────────────────────────────
def scanned_tfs():
    """ТФ для калибровки баров и скана Этапа B: primary SCOUT_TF первым + доп. из SCOUT_TFS (1h — по тумблеру
    SCOUT_TF_1H_ENABLED). Дедуп, порядок сохранён, неизвестные имена отброшены (страховка от битого env)."""
    known = ("4h", "1h", "15m", "5m")
    out = [SCOUT_TF] if SCOUT_TF in known else ["4h"]
    for t in (SCOUT_TFS or "").split(","):
        t = t.strip()
        if not t or t in out or t not in known:
            continue
        if t == "1h" and not SCOUT_TF_1H_ENABLED:
            continue
        out.append(t)
    return out
