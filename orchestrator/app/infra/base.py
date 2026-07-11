"""InfraDriver — абстракция инфраструктуры (шов S5, seams.md).

Оркестратор управляет контейнерами ботов ТОЛЬКО через этот интерфейс: тело оркестратора не знает,
Railway под ним, Docker или фейк. Контракт (S5): deploy(spec)→infra_ref · destroy(infra_ref) ·
status(infra_ref). Заглушка = явная ошибка + conformance-тест (молчаливых полудорог нет).

infra_ref = «railway:{project}:{svc}» — провайдер и проект зашиты в формат СРАЗУ (SCL8: квота
сервисов/проект вынудит мульти-проект, миграция формата потом дорога). destroy идемпотентен:
отсутствие сервиса = успех (OPS5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeploySpec:
    """Что деплоить. name детерминировано ядром как mfc-inst-{id} (усыновление по имени, S3/S5)."""

    image: str
    name: str
    env: dict[str, str] = field(default_factory=dict)


class InfraStatus:
    """Нормализованное состояние сервиса у провайдера (драйвер приводит родное к этим значениям)."""

    RUNNING = "running"
    STOPPED = "stopped"
    ABSENT = "absent"  # сервиса нет (удалён/не создавался) — для teardown это успех
    UNKNOWN = "unknown"


class InfraError(Exception):
    """Инфра ответила ошибкой (сеть/GraphQL/квота). Оркестратор: backoff + release lease (OPS16)."""


def make_ref(project: str, svc: str) -> str:
    """Собрать infra_ref. Провайдер пока один (railway) — зашит в формат осознанно (SCL8)."""
    return f"railway:{project}:{svc}"


def parse_ref(infra_ref: str) -> tuple[str, str, str]:
    """Разобрать infra_ref → (provider, project, svc). Кидает ValueError на кривой ссылке."""
    parts = infra_ref.split(":")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"кривой infra_ref: {infra_ref!r}")
    provider, project, svc = parts
    return provider, project, svc


class InfraDriver(ABC):
    """Контракт шва S5. Любой драйвер (Railway/Docker/Fake) обязан пройти conformance-тест."""

    @abstractmethod
    def deploy(self, spec: DeploySpec) -> str:
        """Создать/обновить сервис бота → infra_ref. Идемпотентно по имени (усынови-или-создай)."""

    @abstractmethod
    def destroy(self, infra_ref: str) -> None:
        """Снести сервис. Идемпотентно: отсутствие сервиса = успех (OPS5)."""

    @abstractmethod
    def status(self, infra_ref: str) -> str:
        """Состояние сервиса (InfraStatus.*). ABSENT, если сервиса нет."""
