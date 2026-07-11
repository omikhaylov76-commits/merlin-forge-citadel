# -*- coding: utf-8 -*-
"""logging_.trade_logger — журналирование.

В скелете (Веха 1) — общий настроенный логгер с UTC-таймстампами, которым точки
входа пишут старт/heartbeat. Запись сделок (signals/fills/events в CSV+БД) — позже.
"""
import logging
import sys
import time

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name="pifagor"):
    """Вернуть настроенный логгер (UTC-время, stdout). Идемпотентно."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(_FORMAT)
    formatter.converter = time.gmtime  # UTC, не локальное время
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
