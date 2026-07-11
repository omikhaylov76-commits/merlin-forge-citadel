"""FakeDriver — in-memory реализация InfraDriver для тестов и локального сквозняка.

В сеть не ходит. Идемпотентен по имени: повторный deploy того же name усыновляет существующий
сервис (перезапись spec — как redeploy). Умеет инъектировать отказы (fail_next) — так проверяется
backoff/release оркестратора при недоступной инфре (OPS16), без реального Railway.
"""

from __future__ import annotations

from app.infra.base import DeploySpec, InfraDriver, InfraError, InfraStatus, make_ref, parse_ref


class FakeDriver(InfraDriver):
    def __init__(self, project: str = "fake") -> None:
        self._project = project
        self._services: dict[str, DeploySpec] = {}  # name → последний задеплоенный spec
        self.fail_next = 0  # уронить InfraError на ближайших N вызовах (инъекция отказа инфры)

    def _maybe_fail(self) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise InfraError("инъецированный отказ инфры (FakeDriver)")

    def deploy(self, spec: DeploySpec) -> str:
        self._maybe_fail()
        self._services[spec.name] = spec  # усыновление по имени: перезапись идемпотентна
        return make_ref(self._project, spec.name)

    def destroy(self, infra_ref: str) -> None:
        self._maybe_fail()
        _, _, svc = parse_ref(infra_ref)
        self._services.pop(svc, None)  # нет сервиса — уже успех (идемпотентно, OPS5)

    def status(self, infra_ref: str) -> str:
        _, _, svc = parse_ref(infra_ref)
        return InfraStatus.RUNNING if svc in self._services else InfraStatus.ABSENT
