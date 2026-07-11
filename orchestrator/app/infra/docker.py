"""DockerDriver — заглушка плана Б (ADR-0003, seams S5).

Провайдер v1 — Railway; Docker остаётся запасным путём на случай пересмотра. Пока каждый метод —
явный NotImplementedError: заглушка обязана быть шумной (молчаливых полудорог нет, seams). Включение
= реализация методов + прогон общего conformance-теста, который уже гвоздит эту заглушку.
"""

from __future__ import annotations

from app.infra.base import DeploySpec, InfraDriver

_NOT_YET = "DockerDriver — план Б (ADR-0003); не реализован. Провайдер v1 — Railway."


class DockerDriver(InfraDriver):
    def deploy(self, spec: DeploySpec) -> str:
        raise NotImplementedError(_NOT_YET)

    def destroy(self, infra_ref: str) -> None:
        raise NotImplementedError(_NOT_YET)

    def status(self, infra_ref: str) -> str:
        raise NotImplementedError(_NOT_YET)
