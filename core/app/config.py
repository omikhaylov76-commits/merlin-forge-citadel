"""Конфигурация ядра. Значения — из окружения (12-factor); секреты в git не попадают.

Почему pydantic-settings: единая типобезопасная точка чтения env вместо разбросанных
os.getenv. extra="ignore" — чтобы orchestrator-only переменные (MF_MASTER_PRIVATE_KEY,
RAILWAY_API_TOKEN) в общем .env не роняли конфиг ядра: ядро их не читает и знать не должно.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: str = "dev"          # dev | staging | prod
    database_url: str = ""    # заполняется в шаге 2 (Alembic + сессии)
    log_level: str = "INFO"


def get_settings() -> Settings:
    # Отдельная функция — точка подмены в тестах (FastAPI dependency_overrides).
    return Settings()
