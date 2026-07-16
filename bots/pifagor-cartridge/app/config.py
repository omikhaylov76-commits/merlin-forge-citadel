"""Конфиг картриджа Пифагора — вход по Контракту Бота v1 (env при старте контейнера).

Две группы env:
1. MF_* — сторона Контракта (адрес ядра, токен инстанса, каденции). Как у эталона `bots/paper-bot`.
2. Пифагор-side — где лежит БД воркера (та же, что читает родной дашборд). Значения берём из
   ВЕНДОРЕННОГО `config.ops` (DATABASE_URL/DB_PATH) — один источник с воркером, без дубля env.

Секретов биржи здесь НЕТ: адаптер только ЧИТАЕТ БД воркера и транслирует команды в опубликованные
контролы (config/kill-switch). Ключи нужны воркеру (config.validate), не адаптеру. Минимум
зависимостей: os.environ + dataclass, без pydantic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

CONTRACT_VERSION = "v1"  # декларируется в heartbeat (ядро в v1 только записывает; scout-канал ADR-0016)


@dataclass(frozen=True)
class CartridgeConfig:
    instance_id: str
    instance_token: str          # скоуп: свой инстанс (шлём телеметрию/берём команды)
    core_url: str                # MF_CORE_URL — база API ядра (шов S4)
    tick_interval_s: float       # период оборота цикла (телеметрия/команды)
    heartbeat_interval_s: float  # не реже раза в 60с (Контракт) — потолок 60
    poll_wait_s: int             # окно long-poll команд
    telemetry_retries: int       # попыток на транзиентный сбой пуша (backoff), потом best-effort
    backoff_base_s: float        # база экспоненты backoff
    backoff_cap_s: float         # потолок паузы backoff


def from_env() -> CartridgeConfig:
    return CartridgeConfig(
        instance_id=os.environ["MF_INSTANCE_ID"],
        instance_token=os.environ["MF_INSTANCE_TOKEN"],
        core_url=os.environ.get("MF_CORE_URL", "http://127.0.0.1:8000"),
        tick_interval_s=float(os.environ.get("MF_TICK_S", "5")),
        # Контракт: heartbeat не реже раза в 60с — потолок 60 (иначе ложные stale/dead у часового).
        heartbeat_interval_s=min(float(os.environ.get("MF_HEARTBEAT_S", "30")), 60.0),
        poll_wait_s=int(os.environ.get("MF_POLL_WAIT_S", "25")),
        telemetry_retries=int(os.environ.get("MF_TELEMETRY_RETRIES", "3")),
        backoff_base_s=float(os.environ.get("MF_BACKOFF_BASE_S", "0.5")),
        backoff_cap_s=float(os.environ.get("MF_BACKOFF_CAP_S", "8")),
    )
