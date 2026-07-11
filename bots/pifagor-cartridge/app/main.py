"""Точка входа картриджа: env Контракта → CoreClient + PifagorReader → цикл (python -m app.main).

Read-only обёртка (ADR-0001) поверх вендоренного снимка @b75bd17: движок не правим, состояние читаем
через build_monitor, команды транслируем в config/kill-switch. БЕЗ реальных ключей/торговли в этом
режиме (LIVE_TRADING_ENABLED=0 / BYBIT_DEMO=1 — дефолты Пифагора; go-live отдельным гейтом).

Мягкая остановка по SIGINT/SIGTERM. Расположение вендора — env PIFAGOR_HOME (в образе /pifagor).
"""

from __future__ import annotations

import logging
import signal
import threading

from app.bot import PifagorCartridge
from app.client import CoreClient
from app.config import from_env
from app.reader import PifagorReader

log = logging.getLogger("mfc.pifagor-cartridge")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = from_env()
    reader = PifagorReader()  # БД воркера — из вендоренного config.ops (DATABASE_URL/DB_PATH)
    bot = PifagorCartridge(CoreClient(base_url=cfg.core_url, token=cfg.instance_token), reader, cfg)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    log.info("pifagor-cartridge запущен: instance=%s core=%s", cfg.instance_id, cfg.core_url)
    try:
        bot.run(stop)
    finally:
        reader.close()


if __name__ == "__main__":
    main()
