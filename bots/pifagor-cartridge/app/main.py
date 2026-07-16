"""Точка входа картриджа: env Контракта → CoreClient + PifagorReader → цикл (python -m app.main).

Read-only обёртка (ADR-0001) поверх вендоренного снимка @b75bd17: движок не правим, состояние читаем
через build_monitor, команды транслируем в config/kill-switch. БЕЗ реальных ключей/торговли в этом
режиме (LIVE_TRADING_ENABLED=0 / BYBIT_DEMO=1 — дефолты Пифагора; go-live отдельным гейтом).

Мягкая остановка по SIGINT/SIGTERM. Расположение вендора — env PIFAGOR_HOME (в образе /pifagor).
"""

from __future__ import annotations

import logging
import os
import signal
import threading

from app.bot import PifagorCartridge
from app.client import CoreClient
from app.config import from_env
from app.reader import PifagorReader

log = logging.getLogger("mfc.pifagor-cartridge")


def _make_scout_reader(cfg, worker_reader):
    """ScoutReader при ДВУХ условиях (defense-in-depth, не включать на флоте): явный MF_SCOUT_PUSH=1
    (ставит start.sh при SCOUT_ENABLED=1) И существование scout.db. На флоте флага нет → None,
    scout-пуша нет (случайный scout.db сам по себе не включит). Сбой init не роняет картридж."""
    if os.environ.get("MF_SCOUT_PUSH") != "1":
        return None
    if not cfg.scout_db_path or not os.path.exists(cfg.scout_db_path):
        return None
    try:
        from app.scout_reader import ScoutReader
        return ScoutReader(
            scout_db_path=cfg.scout_db_path, worker_reader=worker_reader,
            detector_version=cfg.detector_version, producer=cfg.scout_producer,
        )
    except Exception:  # noqa: BLE001
        log.exception("scout_reader init упал — scout-канал выключен")
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = from_env()
    reader = PifagorReader()  # БД воркера — из вендоренного config.ops (DATABASE_URL/DB_PATH)
    scout_reader = _make_scout_reader(cfg, reader)
    if scout_reader is not None:
        log.info("scout-канал ВКЛ: читаю %s", cfg.scout_db_path)
    bot = PifagorCartridge(
        CoreClient(base_url=cfg.core_url, token=cfg.instance_token), reader, cfg,
        scout_reader=scout_reader,
    )

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    log.info("pifagor-cartridge запущен: instance=%s core=%s", cfg.instance_id, cfg.core_url)
    try:
        bot.run(stop)
    finally:
        reader.close()
        if scout_reader is not None:
            scout_reader.close()


if __name__ == "__main__":
    main()
