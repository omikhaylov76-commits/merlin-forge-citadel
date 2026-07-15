"""Точка входа оркестратора: конфиг → драйвер → CoreClient → цикл воркера.

Запуск: `python -m app.main` (нужны CORE_API_URL, ORCHESTRATOR_TOKEN, DRIVER). Мягкая остановка —
по SIGINT/SIGTERM (stop-событие). Драйвер выбирается конфигом (fake для сквозняка, railway в бою).
"""

from __future__ import annotations

import logging
import signal
import threading

from app.config import OrchestratorSettings, get_settings
from app.core_client import CoreClient
from app.infra.base import InfraDriver
from app.infra.docker import DockerDriver
from app.infra.fake import FakeDriver
from app.infra.railway import RailwayDriver
from app.worker import run

log = logging.getLogger("mfc.orch")


def build_driver(settings: OrchestratorSettings) -> InfraDriver:
    if settings.driver == "fake":
        return FakeDriver()
    if settings.driver == "docker":
        return DockerDriver()
    # demo-ключи Bybit (если заданы) инжектим в env КАЖДОГО деплоя картриджа — картридж без них не
    # бутится (config.validate). Не в payload ядра (закон №2), а тут, в оркестраторе (#16).
    deploy_env_extra: dict[str, str] = {}
    if settings.bybit_api_key and settings.bybit_api_secret:
        deploy_env_extra["BYBIT_API_KEY"] = settings.bybit_api_key
        deploy_env_extra["BYBIT_API_SECRET"] = settings.bybit_api_secret
    return RailwayDriver(
        api_token=settings.railway_api_token,
        project_id=settings.railway_project_id,
        api_url=settings.railway_api_url,
        environment_id=settings.railway_environment_id,
        registry_username=settings.ghcr_pull_username,
        registry_token=settings.ghcr_pull_token,
        deploy_env_extra=deploy_env_extra,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    driver = build_driver(settings)
    core = CoreClient(base_url=settings.core_api_url, token=settings.orchestrator_token)
    stop = threading.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # мягкая остановка цикла

    log.info("оркестратор запущен: driver=%s core=%s", settings.driver, settings.core_api_url)
    run(
        core,
        driver,
        stop=stop,
        wait=settings.poll_wait_seconds,
        backoff_base=settings.backoff_base_seconds,
        backoff_max=settings.backoff_max_seconds,
    )


if __name__ == "__main__":
    main()
