"""Конфиг картриджа — вход по Контракту Бота v1 (env при старте контейнера, bot-contract.md).

Секретов биржи в paper-режиме нет (EXCHANGE_* игнорируем). Минимум зависимостей: os.environ +
dataclass, без pydantic. MF_INSTANCE_ID/MF_INSTANCE_TOKEN обязательны — иначе картридж не стартует.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

CONTRACT_VERSION = "v1"  # декларируется в heartbeat (ядро в v1 только записывает; scout-канал ADR-0016)


@dataclass(frozen=True)
class BotConfig:
    instance_id: str
    instance_token: str          # скоуп: свой инстанс (шлём телеметрию/берём команды)
    core_url: str                # MF_CORE_URL — база API ядра (шов S4)
    seed: int                    # сид «сделок» — детерминизм (разбор #4)
    tick_interval_s: float       # период оборота цикла (equity/сделки)
    heartbeat_interval_s: float  # не реже раза в 60с (Контракт)
    poll_wait_s: int             # окно long-poll команд


def from_env() -> BotConfig:
    return BotConfig(
        instance_id=os.environ["MF_INSTANCE_ID"],
        instance_token=os.environ["MF_INSTANCE_TOKEN"],
        core_url=os.environ.get("MF_CORE_URL", "http://127.0.0.1:8000"),
        seed=int(os.environ.get("MF_SEED", "42")),
        tick_interval_s=float(os.environ.get("MF_TICK_S", "5")),
        # Контракт: heartbeat не реже раза в 60с — потолок 60 (иначе ложные stale/dead у часового).
        heartbeat_interval_s=min(float(os.environ.get("MF_HEARTBEAT_S", "30")), 60.0),
        poll_wait_s=int(os.environ.get("MF_POLL_WAIT_S", "25")),
    )
