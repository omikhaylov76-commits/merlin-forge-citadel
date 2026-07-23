"""Порция №2 «прогрев held» — boot-шаг ДО старта движка (S8 «Динамо-близнец»).

На редеплое scout.db эфемерна → вселенная провайдера пуста ~18мин (до первого скана), движок
поднимается на дефолте-16: held-позиции НЕ в рабочей вселенной → движок их НЕ ведёт (трейлинг/
таймаут не работают, защита лишь биржевыми стопами). coins.json движок читает ТОЛЬКО на старте
(ADR-0019, не hot-reload) и стартует РАНЬШЕ адаптера → прогрев обязан лечь ДО `engine_supervise`,
а не в tick.

Пишем coins.json из held, чтобы движок поднялся уже с held-вселенной и вёл позиции с 1-й минуты.
0-vendor: held читаем через `PifagorReader(owner=False)` (лок движка НЕ берём — reader.py) из
персист-БД воркера; пишем только адаптерный coins.json (дефолт-бары, per-coin приедут со сканом).
Best-effort: сбой/пустой held → лог + выход 0, боот идёт дальше (движок на дефолте, как раньше).
"""
from __future__ import annotations

import logging

log = logging.getLogger("mfc.pifagor-cartridge")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:  # контракт best-effort: любой сбой → лог + выход 0 (боот не валим)
        from app.config import from_env
        from app.dynamic_universe import prewarm_coins_from_held
        cfg = from_env()  # env неполон → KeyError тоже сюда (движок на дефолте)
        if not cfg.dynamic_enabled or not cfg.dynamic_coins_path:
            return 0                                 # динамика выкл (флот/paper) — прогрева нет
        from app import mapper
        from app.reader import PifagorReader
        reader = PifagorReader()                     # owner=False: лок движка НЕ берём (reader.py)
        try:
            held = mapper.held_symbols(reader.snapshot())
        finally:
            reader.close()
        if not prewarm_coins_from_held(cfg.dynamic_coins_path, held):
            log.info("prewarm-held: held пуст → прогрева нет (движок на дефолте до скана)")
    except Exception:  # noqa: BLE001 — env/БД/схема/прочее → не валим боот (движок на дефолте)
        log.exception("prewarm-held: сбой — пропуск (движок поднимется на дефолте)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
