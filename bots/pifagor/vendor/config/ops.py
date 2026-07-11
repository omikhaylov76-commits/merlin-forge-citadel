# -*- coding: utf-8 -*-
"""Эксплуатация V8.1 (docs/04 §5): секреты, demo/mainnet домены, интервалы, пути.

Секреты — ТОЛЬКО из переменных окружения, никогда не в коде.
"""
import os

from ._env import env_bool, env_int, env_str

# ── Секреты Bybit (env-only) ─────────────────────────────────────────────────
BYBIT_API_KEY = env_str("BYBIT_API_KEY", "")
BYBIT_API_SECRET = env_str("BYBIT_API_SECRET", "")

# demo=True -> домен api-demo.bybit.com. Для боевого счёта BYBIT_DEMO=0.
USE_DEMO = env_bool("BYBIT_DEMO", True)
# ПРЕДОХРАНИТЕЛЬ MAINNET (5.5b): боевой счёт (BYBIT_DEMO=0) разрешён ТОЛЬКО при явном ALLOW_MAINNET=1.
# Иначе config.validate() прерывает старт — чтобы случайно забытая/перепутанная переменная не увела
# бота на реальные деньги. Demo (дефолт) — без трения. Включать вместе с осознанным переходом в Вехе 6.
ALLOW_MAINNET = env_bool("ALLOW_MAINNET", False)

# Домены: demo и mainnet — РАЗНЫЕ (не только ключ), переключатель по USE_DEMO.
REST_DEMO = "https://api-demo.bybit.com"
REST_MAINNET = "https://api.bybit.com"
WS_PRIVATE_DEMO = "wss://stream-demo.bybit.com/v5/private"
WS_PRIVATE_MAINNET = "wss://stream.bybit.com/v5/private"
WS_PUBLIC_LINEAR = "wss://stream.bybit.com/v5/public/linear"  # публичные данные demo=mainnet

REST_URL = REST_DEMO if USE_DEMO else REST_MAINNET
WS_PRIVATE_URL = WS_PRIVATE_DEMO if USE_DEMO else WS_PRIVATE_MAINNET

# ── Рынок / расписание ────────────────────────────────────────────────────────
CATEGORY = "linear"     # USDT-перпы
INTERVAL = "240"        # 4h в формате Bybit (минуты) — таймфрейм сигнала
EXEC_POLL_SEC = env_int("EXEC_POLL_SEC", 900)   # номинальная каденция 15m-цикла (=EXEC_INTERVAL*60)
HEARTBEAT_SEC = env_int("HEARTBEAT_SEC", 300)   # healthcheck-лог
EQHIST_INTERVAL_MS = env_int("EQHIST_INTERVAL_MS", 3_600_000)   # каденция точки кривой капитала (1ч; ~24 строки/сут)
# 15m-таймфрейм исполнения (формат Bybit, минуты). Парити: ровно "15" (связан с
# config.strategy.EXEC_TF='15m'); ≠"15" допустимо как knob, но вне честных OOS-чисел (ре-бэктест).
EXEC_INTERVAL = env_str("EXEC_INTERVAL", "15")
# Сколько 15m-свечей тянуть за раз: сброс форм-свечи + окно для буфера/бэкафилла.
EXEC_KLINE_LIMIT = env_int("EXEC_KLINE_LIMIT", 200)
# Сколько 4h-свечей (сигнал) тянуть за раз = макс Bybit (1000). Глубокий warm-up EMA200 →
# в проде кормим ~999 закрытых баров, rel_err vs EMA200 движка ~1e-7 (≈ полная история).
SIGNAL_KLINE_LIMIT = env_int("SIGNAL_KLINE_LIMIT", 1000)
# ПРЕДОХРАНИТЕЛЬ боевой торговли (ф.5.2 п.3c): OFF ⇒ цикл считает+логирует «поставил БЫ», ордеров НЕ ставит
# (защита «ставит-но-не-ведёт» до готовности ведения, под-шаг 4). Включать ТОЛЬКО на деплое demo (5.5).
LIVE_TRADING_ENABLED = env_bool("LIVE_TRADING_ENABLED", False)

# ── Аварийное управление (дашборд «Настройки», ADR 0011) ──────────────────────
# Пауза — «не открывать новые сетапы». Рантайм-крутилка (config_state), читается движком (Веха 5).
# Дефолт ВЫКЛ; непустое нераспознанное значение env -> ENV_ERRORS (как Shorts/EMA), а не молча False.
PAUSE_ENABLED = env_bool("PAUSE_ENABLED", False)

# ── Тёплый старт (warm-start, Веха 5.8, ADR 0013) ─────────────────────────────
# WARM_ON_START — авто-подхват уже-живых сетапов при запуске/рестарте воркера. Дефолт ВЫКЛ (осознанное
# ослабление no-backfill; включать явно). Авто берёт ТОЛЬКО auto_eligible (нетронутый PENDING) — см. ADR 0013.
WARM_ON_START = env_bool("WARM_ON_START", False)
# WARM_MAX_AGE_BARS — окно «свежести пробоя» для подхвата (закрытые 4h-бары). Дефолт 72 (= execution.TIMEOUT_BARS:
# committed-сетап старше таймаута всё равно закрыт). Крутилка strategy.warm.classify(max_age_bars=...).
WARM_MAX_AGE_BARS = env_int("WARM_MAX_AGE_BARS", 72)

# ── WS-тень (Веха 5.2 п6, measure-first; ADR 0014 — планируется) ──────────────
# Наблюдательный приватный execution-стрим для ЗАМЕРА края Вехи 5.6 (лаг опроса + slip). Дефолт ВЫКЛ ⇒
# тень не поднимается, воркер 1:1 как сейчас; торговый путь она НЕ трогает (пишет только в ws_exec_log через
# WsExecFacade, под-шаг 1). Читает те же BYBIT_API_KEY/SECRET, что и торговля — новых ключей НЕ требует.
WS_SHADOW_ENABLED = env_bool("WS_SHADOW_ENABLED", False)
WS_PING_SEC = env_int("WS_PING_SEC", 20)              # keepalive-ping приватного стрима (Bybit рвёт без пинга)
WS_STALENESS_MULT = env_int("WS_STALENESS_MULT", 3)   # is_alive() дедлайн свежести = MULT*WS_PING_SEC (half-open → мёртв)

# ── БД ────────────────────────────────────────────────────────────────────────
DATABASE_URL = env_str("DATABASE_URL", "")  # Postgres на Railway; пусто -> SQLite по DB_PATH

# ── Пути (де-хардкод из движка; env-override). Дефолты относительно корня репо. ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = env_str("DATA_DIR", os.path.join(_ROOT, "data"))
STATE_PATH = env_str("STATE_PATH", os.path.join(_ROOT, "state_data"))
LOG_PATH = env_str("LOG_PATH", os.path.join(_ROOT, "logs"))
DB_PATH = env_str("DB_PATH", os.path.join(_ROOT, "pifagor.db"))
LOCK_PATH = env_str("LOCK_PATH", os.path.join(_ROOT, "pifagor.lock"))
# Сколько секунд ждать освобождения advisory-lock БД при OVERLAP-передеплое Railway (старый воркер ещё
# держит лок, пока Railway его не снял) перед тем как сдаться. Не падаем сразу — иначе дедлок: новый
# крэшит → Railway не снимает старый → новый снова крэшит (5.5c-находка на деплое). 0 = не ждать (тесты).
LOCK_WAIT_SEC = env_int("LOCK_WAIT_SEC", 150)
