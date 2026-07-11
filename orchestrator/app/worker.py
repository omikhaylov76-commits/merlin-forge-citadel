"""Worker оркестратора: аренда jobs → исполнение через InfraDriver → ack (швы S3↔S5, ADR-0009).

process_once — один заход: арендовать (long-poll), ИСПОЛНИТЬ по kind, ОТЧИТАТЬСЯ (ack). Исполнение
и ack РАЗВЕДЕНЫ: `_execute` ловит ошибки исполнения драйвера и возвращает параметры ack; сам
`core.ack` зовётся ОТДЕЛЬНО, и его сбой (транспорт к ядру) ПРОБРАСЫВАется в `run` (backoff), а НЕ
переклассифицирует исход: упавший `ack('done')` превратил бы здоровый деплой в failed тем же
валидным nonce (fencing бессилен) → сервис-сирота. Аренда протухнет → реклейм → повтор (усыновление
по имени идемпотентно, OPS2).

Отображение исходов ИСПОЛНЕНИЯ на ack (модель отказов seams):
- успех                → done (deploy: {infra_ref}; teardown: пусто)
- InfraError           → release: инфра лежит, отпуск без штрафа attempts (OPS16), очередь вернёт
- прочее исключение    → failed+terminal: неустранимо (кривой payload; в Ф2 — расшифровка ключа)
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


def _execute(driver: InfraDriver, lease: Lease) -> dict:
    """Исполнить job драйвером → параметры ack (result/detail/terminal). Ловит ошибки ИСПОЛНЕНИЯ,
    НЕ транспорта ack. Причина в detail — КОД/тип, не сырой str(exc): тело/трейс могут нести ключ
    (закон №2), особенно на decrypt-пути Ф2."""
    try:
        if lease.kind == "deploy":
            p = lease.payload
            spec = DeploySpec(image=p["image"], name=p["name"], env=p.get("env") or {})
            infra_ref = driver.deploy(spec)  # усынови-или-создай по имени → infra_ref
            return {"result": "done", "detail": {"infra_ref": infra_ref}}
        if lease.kind == "teardown":
            infra_ref = lease.payload.get("infra_ref")
            if infra_ref:
                driver.destroy(infra_ref)  # идемпотентно: нет сервиса = успех (OPS5)
            return {"result": "done"}
        return {
            "result": "failed", "terminal": True,
            "detail": {"reason": f"unknown_kind:{lease.kind}"},
        }
    except InfraError as exc:
        # Инфра недоступна: отпуск без штрафа, ядро вернёт в очередь под backoff (OPS16).
        log.warning("infra недоступна по job %s: %s — release", lease.id, exc)
        return {"result": "release", "detail": {"reason": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — любой неустранимый сбой исполнения = terminal fail
        # Кривой payload / (Ф2) расшифровка ключа: без ретраев. Логируем ТИП, не тело (закон №2).
        reason = type(exc).__name__
        log.error("неустранимый сбой по job %s: %s — failed terminal", lease.id, reason)
        return {"result": "failed", "terminal": True, "detail": {"reason": reason}}


def process_once(core: CoreClient, driver: InfraDriver, *, wait: int = 25) -> bool:
    """Один заход: арендовать → исполнить → ack. False, если за окно ничего не досталось.

    ack ВНЕ try исполнения: его сбой (ядро недоступно) пробрасывается в run (backoff), НЕ
    переклассифицирует деплой в failed (BLOCKER-1). Повтор безопасен — усыновление по имени.
    """
    lease = core.lease_next(wait=wait)
    if lease is None:
        return False
    outcome = _execute(driver, lease)
    core.ack(job_id=lease.id, lease_nonce=lease.lease_nonce, **outcome)
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
    """Цикл воркера до stop. Пусто — сразу следующий заход (long-poll уже проспал). Падение ядра
    (lease/ack кинул) — backoff с ростом (не молотим недоступное ядро)."""
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
