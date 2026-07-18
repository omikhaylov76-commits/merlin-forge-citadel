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


def _make_dynamic_provider(cfg, scout_reader):
    """DynamicUniverse при dynamic_enabled=1 И scout_reader (Борс = свой скаут; S8). Иначе None
    (флот/paper: динамика ВЫКЛ, геном). Читает печку через scout_reader. Сбой init не роняет."""
    if not cfg.dynamic_enabled or scout_reader is None:
        return None
    # ГЕЙТ ВЕХИ 2 (триппвайр, fail-closed): пин символа с позицией («б» ADR-0019) НЕ реализован.
    # Пока пина нет, динамика + ЖИВАЯ торговля запрещены (рестарт бросил бы позицию). Комбо
    # DYNAMIC_ENABLED=1 + LIVE_TRADING_ENABLED=1 → провайдер НЕ активируется (движок на дефолте).
    if os.environ.get("LIVE_TRADING_ENABLED") == "1":
        log.error("динамика ОТКЛЮЧЕНА: LIVE_TRADING_ENABLED=1 без пина позиций — гейт Вехи 2 "
                  "(рестарт бросил бы позицию); движок на дефолтной вселенной (ADR-0019).")
        return None
    try:
        from app.dynamic_universe import DynamicUniverse
        return DynamicUniverse(cfg, scout_reader)
    except Exception:  # noqa: BLE001
        log.exception("dynamic provider init упал — динамика выключена")
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = from_env()
    reader = PifagorReader()  # БД воркера — из вендоренного config.ops (DATABASE_URL/DB_PATH)
    scout_reader = _make_scout_reader(cfg, reader)
    if scout_reader is not None:
        log.info("scout-канал ВКЛ: читаю %s", cfg.scout_db_path)
        # Разведка-стол (страж 1): фоновый boot-fetch настроек дозора из ядра → файл-оверрайд →
        # gen-рестарт скаута супервизором. НЕ блокирует движок/скаут (уже бегут на генных дефолтах).
        from app.scout_overrides import boot_fetch
        threading.Thread(
            target=boot_fetch, args=(cfg.core_url, cfg.instance_token),
            name="scout-boot-fetch", daemon=True,
        ).start()
    provider = _make_dynamic_provider(cfg, scout_reader)
    if provider is not None:
        log.info("dynamic-канал ВКЛ: вселенная из печки → %s (кап %d)",
                 cfg.dynamic_coins_path, cfg.dynamic_stack_max)
        # ADR-0020 D1: фоновый ПЕРИОДИЧЕСКИЙ re-fetch критериев → JSON, провайдер читает живьём.
        # НЕ блокирует провайдер (он на ген-дефолтах, пока файла нет). Без файла-пути — скип.
        if cfg.dynamic_criteria_path:
            from app.dynamic_overrides import refetch_loop
            threading.Thread(
                target=refetch_loop,
                args=(cfg.core_url, cfg.instance_token, cfg.dynamic_criteria_path),
                kwargs={"interval": cfg.dynamic_refetch_s},
                name="dynamic-refetch", daemon=True,
            ).start()
    bot = PifagorCartridge(
        CoreClient(base_url=cfg.core_url, token=cfg.instance_token), reader, cfg,
        scout_reader=scout_reader, provider=provider,
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
