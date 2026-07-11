"""Worker оркестратора: аренда jobs → исполнение через InfraDriver → ack (швы S3↔S5, ADR-0009).

process_once — один заход (тестируемая единица): арендовать (long-poll), исполнить по kind, ack.
run — цикл с backoff при недоступном ядре и мягкой остановкой по stop-событию.

Отображение исходов на ack (модель отказов seams):
- успех                → done (deploy: {infra_ref}; teardown: пусто)
- InfraError           → release: инфра лежит, отпуск без штрафа attempts (OPS16), очередь вернёт
- прочее исключение    → failed+terminal: неустранимо (кривой payload/расшифровка), без ретраев
- неизвестный kind     → failed+terminal (защита от мусора в очереди)

Fencing-nonce аренды возвращаем ядру на ack (OPS2). Драйвер синхронный → worker синхронный; разгон
на N воркеров — крутилкой конфига (SCL6), не здесь.
"""

from __future__ import annotations

import logging
import threading

from app.core_client import CoreClient, Lease
from app.infra.base import DeploySpec, InfraDriver, InfraError

log = logging.getLogger("mfc.orch.worker")


def _do_deploy(core: CoreClient, driver: InfraDriver, lease: Lease) -> None:
    p = lease.payload
    spec = DeploySpec(image=p["image"], name=p["name"], env=p.get("env") or {})
    infra_ref = driver.deploy(spec)  # усынови-или-создай по имени; вернёт infra_ref
    core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, result="done",
             detail={"infra_ref": infra_ref})


def _do_teardown(core: CoreClient, driver: InfraDriver, lease: Lease) -> None:
    infra_ref = lease.payload.get("infra_ref")
    if infra_ref:
        driver.destroy(infra_ref)  # идемпотентно: нет сервиса = успех (OPS5)
    core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, result="done")


def process_once(core: CoreClient, driver: InfraDriver, *, wait: int = 25) -> bool:
    """Один заход: арендовать и обработать один job. False, если за окно ничего не досталось."""
    lease = core.lease_next(wait=wait)
    if lease is None:
        return False
    try:
        if lease.kind == "deploy":
            _do_deploy(core, driver, lease)
        elif lease.kind == "teardown":
            _do_teardown(core, driver, lease)
        else:
            core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, result="failed",
                     terminal=True, detail={"reason": f"неизвестный kind: {lease.kind}"})
    except InfraError as exc:
        # Инфра недоступна: отпуск без штрафа, ядро вернёт в очередь под backoff (OPS16).
        log.warning("infra недоступна по job %s: %s — release", lease.id, exc)
        core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, result="release",
                 detail={"reason": str(exc)})
    except Exception as exc:  # noqa: BLE001 — намеренно широко: неустранимый сбой = terminal fail
        # Кривой payload / расшифровка ключа: без ретраев (для teardown ядро всё равно вернёт).
        log.exception("неустранимый сбой по job %s — failed terminal", lease.id)
        core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, result="failed",
                 terminal=True, detail={"reason": str(exc)})
    return True


def run(
    core: CoreClient,
    driver: InfraDriver,
    *,
    stop: threading.Event,
    wait: int = 25,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
) -> None:
    """Цикл воркера до stop. Пусто — сразу следующий заход (long-poll уже проспал). Падение ядра —
    backoff с ростом (не молотим недоступное ядро)."""
    backoff = backoff_base
    while not stop.is_set():
        try:
            process_once(core, driver, wait=wait)
            backoff = backoff_base  # ядро отвечает — сбрасываем backoff
        except Exception:  # noqa: BLE001 — ядро недоступно (lease/ack кинул): ждём и растём
            log.exception("worker: заход упал — backoff %.1fs", backoff)
            stop.wait(backoff)
            backoff = min(backoff * 2, backoff_max)
    log.info("worker остановлен")
