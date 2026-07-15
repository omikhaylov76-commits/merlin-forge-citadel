"""Конфигурация оркестратора — из окружения (12-factor), как в ядре. Секреты в git не попадают.

Оркестратор — единственный держатель приватной половины master-пары (ADR-0004/0010) и токена
Railway; в v1 paper-bot секретов биржи нет (конверт — Ф2), но переменные заведены заранее.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    core_api_url: str = "http://127.0.0.1:8000"  # база internal API ядра (шов S3)
    orchestrator_token: str = ""                 # opaque-токен принципала orchestrator (ADR-0008)
    driver: str = "fake"                         # fake | railway | docker
    # RailwayDriver (боевой прогон — отдельная веха): токен + проект (формат infra_ref, SCL8).
    railway_api_token: str = ""
    railway_project_id: str = ""
    railway_api_url: str = "https://backboard.railway.app/graphql/v2"
    railway_environment_id: str = ""  # для serviceInstanceDeploy; пусто → драйвер найдёт production
    # ghcr pull для ПРИВАТНОГО образа картриджа (#46): username + PAT (read:packages). Только env.
    ghcr_pull_username: str = ""
    ghcr_pull_token: str = ""
    # Аренда: окно long-poll и параметры backoff при отказе инфры (OPS16).
    poll_wait_seconds: int = 25
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0

    @model_validator(mode="after")
    def _driver_known(self) -> "OrchestratorSettings":
        if self.driver not in ("fake", "railway", "docker"):
            raise ValueError(f"неизвестный driver: {self.driver!r}")
        return self


def get_settings() -> OrchestratorSettings:
    return OrchestratorSettings()
