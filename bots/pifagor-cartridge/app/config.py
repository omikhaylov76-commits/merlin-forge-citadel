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

CONTRACT_VERSION = "v1"  # декларируется в heartbeat; scout-канал ADR-0016 (ядро только пишет)


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
    # scout-канал (ADR-0016 #52): читается ТОЛЬКО если scout.db существует (скаут включён #51).
    # Дефолты — чтобы старые конструкторы (тесты/эталон) не ломались; from_env заполняет из env.
    scout_db_path: str = ""      # путь к ОТДЕЛЬНОЙ scout.db (пусто/нет файла → scout-пуша нет)
    scout_interval_s: float = 60.0   # каденция проверки нового scan_ts (сканы редки)
    detector_version: str = "pifagor-v81-b75bd17"  # версия детектора движка (снимок b75bd17)
    scout_producer: str = "pifagor-scout"          # producer снимка (в режиме представителя)
    # dynamic-universe (ADR-0019, S8): бот берёт вселенную из печки. Геном, дефолт ВЫКЛ (как scout).
    # Провайдер пишет coins.json (= COINS_CONFIG_PATH разъёма движка).
    dynamic_enabled: bool = False
    # F-lookahead v3 (подпись Куратора 2026-07-22): ИСТОЧНИК торговой вселенной.
    #   "scout"  — прежний путь: стек = скаут-находки tracking/ready (дефолт, байт-в-байт);
    #   "engine" — вселенная ОТ ДВИЖКА: warm.classify по курированному scout_list берёт placeable
    #              (лечит misalignment «скаут-скор ≠ движок-placeable»). Только Борсу (роль).
    dynamic_source: str = "scout"
    dynamic_coins_path: str = ""       # путь coins.json (провайдер↔разъём движка); пусто → off
    dynamic_stack_max: int = 10        # предохранитель: макс монет (ген-дефолт; канал ADR-0020)
    dynamic_enter_scans: int = 1       # гистерезис: сканов до входа
    dynamic_exit_scans: int = 2        # гистерезис: пропущенных сканов до выхода (слот свободен)
    dynamic_fresh_bars: int = 0        # свежесть ≤ N баров (0 = выкл; ген-дефолт; канал ADR-0020)
    dynamic_min_score: int = 0         # доп-порог скора поверх дозорного (0 = выкл; канал ADR-0020)
    dynamic_min_write_s: float = 30.0  # min-интервал записи coins.json/gen (анти-thrash рестарта)
    # ADR-0020 «Динамика»: критерии (min_score/stack_max/fresh_bars) ядро отдаёт по /self; фоновый
    # re-fetch пишет JSON-файл, провайдер читает его ЖИВЬЁМ. Пусто → провайдер на ген-дефолтах.
    dynamic_criteria_path: str = ""    # путь dynamic_criteria.json (re-fetch↔провайдер)
    dynamic_refetch_s: float = 300.0   # интервал re-fetch критериев из ядра (D1: живое применение)


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
        scout_db_path=os.environ.get(
            "MF_SCOUT_DB_PATH",
            f"{os.environ['PIFAGOR_HOME']}/scout.db" if os.environ.get("PIFAGOR_HOME") else "",
        ),
        scout_interval_s=float(os.environ.get("MF_SCOUT_S", "60")),
        detector_version=os.environ.get("MF_DETECTOR_VERSION", "pifagor-v81-b75bd17"),
        scout_producer=os.environ.get("MF_SCOUT_PRODUCER", "pifagor-scout"),
        # dynamic-universe: гейт как SCOUT_ENABLED (строго "1"); путь = COINS_CONFIG_PATH разъёма
        # (start.sh задаёт его на эфемерном PIFAGOR_HOME ТОЛЬКО при DYNAMIC_ENABLED=1).
        dynamic_enabled=os.environ.get("DYNAMIC_ENABLED") == "1",
        dynamic_source=(os.environ.get("DYNAMIC_SOURCE") or "scout").strip().lower(),
        dynamic_coins_path=os.environ.get(
            "COINS_CONFIG_PATH",
            f"{os.environ['PIFAGOR_HOME']}/coins.json" if os.environ.get("PIFAGOR_HOME") else "",
        ),
        dynamic_stack_max=int(os.environ.get("DYNAMIC_STACK_MAX", "10")),
        dynamic_enter_scans=int(os.environ.get("DYNAMIC_ENTER_SCANS", "1")),
        dynamic_exit_scans=int(os.environ.get("DYNAMIC_EXIT_SCANS", "2")),
        dynamic_fresh_bars=int(os.environ.get("DYNAMIC_FRESH_BARS", "0")),
        dynamic_min_score=int(os.environ.get("DYNAMIC_MIN_SCORE", "0")),
        dynamic_min_write_s=float(os.environ.get("DYNAMIC_MIN_WRITE_S", "30")),
        dynamic_criteria_path=os.environ.get(
            "DYNAMIC_CRITERIA_PATH",
            f"{os.environ['PIFAGOR_HOME']}/dynamic_criteria.json"
            if os.environ.get("PIFAGOR_HOME") else "",
        ),
        dynamic_refetch_s=float(os.environ.get("DYNAMIC_REFETCH_S", "300")),
    )
