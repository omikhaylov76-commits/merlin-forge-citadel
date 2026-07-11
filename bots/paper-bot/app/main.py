"""Точка входа картриджа: env Контракта → CoreClient + PaperEngine → цикл. `python -m app.main`.

Мягкая остановка по SIGINT/SIGTERM. Без реальной биржи/ключей (paper-only).
"""

from __future__ import annotations

import logging
import signal
import threading

from app.bot import PaperBot
from app.client import CoreClient
from app.config import from_env
from app.engine import PaperEngine

log = logging.getLogger("mfc.paper-bot")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = from_env()
    bot = PaperBot(
        CoreClient(base_url=cfg.core_url, token=cfg.instance_token),
        PaperEngine(seed=cfg.seed),
        cfg,
    )
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    log.info("paper-bot запущен: instance=%s core=%s", cfg.instance_id, cfg.core_url)
    bot.run(stop)


if __name__ == "__main__":
    main()
