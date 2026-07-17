"""Оверрайды дозора (Разведка-стол): ядро = durable-истина, картридж = stateless-применитель.

На boot и на команду dozor_apply картридж собирает shell-sourceable файл SCOUT_*-env (супервизор
source'ит его на каждом (ре)старте скаута) + бампает gen-файл (супервизор видит смену gen → мягко
рестартит ТОЛЬКО скаут). Настройкам том НЕ нужен: истина в ядре, картридж её забирает (закон
эталона — каждый бот от Мерлина умеет «забрать свои настройки из ядра»).

СТРАЖИ (директива Куратора):
1. Boot-fetch НЕ блокирует движок/скаут: скаут стартует на генных дефолтах start.sh; fetch ретраится
   фоном, по успеху бампает gen → скаут рестартится с настройками ядра.
2. Анти-инъекция: файл собирается ТОЛЬКО из whitelist SCOUT_*-ключей; значения строго приводятся к
   числу/enum (никогда не пишем сырую строку из сети в sourceable-файл).
3. Скоуп: через канал ходят ТОЛЬКО SCOUT_*-пороги дозора. Движок/риск — никогда (whitelist в коде).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request

log = logging.getLogger("mfc.scout-overrides")

# Страж 2+3: whitelist ключ ядра → SCOUT_*-env (только дозор; движок/риск отсутствуют физически).
_INT = {
    "min_age_days": "SCOUT_MIN_AGE_DAYS",
    "min_turnover_usd": "SCOUT_MIN_TURNOVER_USD",
    "min_history_bars": "SCOUT_MIN_HISTORY_BARS",
    "min_score": "SCOUT_MIN_SCORE",
    "universe_max": "SCOUT_UNIVERSE_MAX",
    "list_max": "SCOUT_LIST_MAX",
    "fresh_bars": "SCOUT_FRESH_BARS",
    "scan_bars": "SCOUT_SCAN_BARS",
    "cal_bars": "SCOUT_CAL_BARS",
    "cal_utc_hour": "SCOUT_CAL_UTC_HOUR",
    "rps": "SCOUT_RPS",
}
_FLOAT = {"max_spread_pct": "SCOUT_MAX_SPREAD_PCT"}
_TF = ("4h", "1h")


def to_env_lines(settings: dict) -> list[str]:
    """Собрать `export SCOUT_*=<число|enum>`. Кривое/чужое — молча пропуск (остаётся генный дефолт).
    НИКОГДА не пишем сырую строку из сети в sourceable-файл (страж 2: только int/float/enum)."""
    out: list[str] = []
    for key, env in _INT.items():
        if key in settings:
            try:
                out.append(f"export {env}={int(settings[key])}")
            except (TypeError, ValueError):
                log.warning("оверрайд %s: не число (%r) — пропуск", key, settings[key])
    for key, env in _FLOAT.items():
        if key in settings:
            try:
                out.append(f"export {env}={float(settings[key])}")
            except (TypeError, ValueError):
                log.warning("оверрайд %s: не число (%r) — пропуск", key, settings[key])
    pt = settings.get("primary_tf")
    if pt in _TF:  # enum-валидация (страж 2)
        out.append(f"export SCOUT_TF={pt}")
    tfs = settings.get("tfs")
    if isinstance(tfs, list):
        good = [t for t in tfs if t in _TF]
        if good:
            out.append(f"export SCOUT_TFS={','.join(good)}")
    return out


def _override_path() -> str:
    return os.environ.get("SCOUT_OVERRIDE_FILE") or (
        f"{os.environ.get('PIFAGOR_HOME', '.')}/scout_overrides.env"
    )


def write_overrides(settings: dict, path: str | None = None) -> int:
    """Атомарно записать файл-оверрайд + бампнуть gen (супервизор увидит смену → рестарт скаута).
    Возвращает число записанных ключей."""
    path = path or _override_path()
    lines = to_env_lines(settings)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)  # атомарная замена (не оставляем полуфайл под source)
    with open(path + ".gen", "w") as f:
        f.write(str(int(time.time() * 1000)))
    log.info("оверрайды дозора записаны: %d ключей → %s", len(lines), path)
    return len(lines)


def fetch_self(core_url: str, token: str, *, timeout: float = 10.0) -> dict:
    """GET /v1/scout/settings/self (instance-токен). Возвращает settings-словарь. Рейзит на сбое."""
    req = urllib.request.Request(
        core_url.rstrip("/") + "/v1/scout/settings/self",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (наш core_url)
        data = json.loads(resp.read())
    return data.get("settings") or {}


def boot_fetch(
    core_url: str, token: str, *, attempts: int = 30, sleep=time.sleep
) -> bool:
    """Страж 1: фоновый boot-fetch. Ретраит fetch, по успеху пишет оверрайды (→ gen-рестарт скаута).
    НЕ блокирует движок/скаут (они уже бегут на дефолтах). True при успехе."""
    for i in range(attempts):
        try:
            write_overrides(fetch_self(core_url, token))
            log.info("boot-fetch настроек дозора удался (попытка %d)", i + 1)
            return True
        except Exception as exc:  # noqa: BLE001 — сеть/ядро недоступно: ретрай, не падаем
            log.info("boot-fetch дозора: попытка %d не удалась (%s), повтор", i + 1, exc)
            sleep(min(2.0 * (i + 1), 30.0))
    log.warning("boot-fetch дозора: попытки исчерпаны — скаут на генных дефолтах (страж 1)")
    return False
