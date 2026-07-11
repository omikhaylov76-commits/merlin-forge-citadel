"""Конфигурация ядра. Значения — из окружения (12-factor); секреты в git не попадают.

Почему pydantic-settings: единая типобезопасная точка чтения env вместо разбросанных
os.getenv. extra="ignore" — чтобы orchestrator-only переменные (MF_MASTER_PRIVATE_KEY,
RAILWAY_API_TOKEN) в общем .env не роняли конфиг ядра: ядро их не читает и знать не должно.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    env: str = "dev"          # dev | staging | prod
    database_url: str = ""    # заполняется в шаге 2 (Alembic + сессии)
    log_level: str = "INFO"
    # URL ядра, по которому бот шлёт телеметрию/берёт команды (MF_CORE_URL в env картриджа, S4).
    core_public_url: str = "http://127.0.0.1:8000"
    # Окно приёма телеметрии по времени бота: |ts−now| < N (S4; защита от мусора/дрейфа часов).
    telemetry_max_skew_seconds: int = 172800  # 48ч (bot-contract)
    # Период тика «часового» (core-scheduler, MFC-002). Порог смерти dead-man = 3×период
    # (деривативно в Scheduler). В env: MFC_… не нужен — читается как SCHEDULER_TICK_SECONDS.
    scheduler_tick_seconds: int = 60
    # Пороги health инстанса для свёртки stale-скан (MFC-003), сек. stale = 3×60с (seams:62);
    # dead — молчит существенно дольше. Это про здоровье ИНСТАНСА, не про сам часовой.
    instance_stale_after_seconds: int = 180
    instance_dead_after_seconds: int = 600
    # jobs-транспорт шва S3 (MFC-004, ADR-0009): аренда, потолок long-poll, лимит попыток deploy.
    job_lease_seconds: int = 60            # срок аренды; протух → job назад в очередь (attempts++)
    job_longpoll_max_wait_seconds: int = 30  # верхний потолок ?wait= у GET /internal/jobs/next
    job_max_deploy_attempts: int = 3       # 3 неудачи deploy → failed + teardown-компенсация (S3)

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> "Settings":
        # stale раньше dead — иначе classify (проверяет dead первым) проглотит весь stale-диапазон.
        if self.instance_stale_after_seconds >= self.instance_dead_after_seconds:
            raise ValueError("instance_stale_after_seconds must be < instance_dead_after_seconds")
        if self.job_max_deploy_attempts < 1:
            raise ValueError("job_max_deploy_attempts must be >= 1")
        return self


def get_settings() -> Settings:
    # Отдельная функция — точка подмены в тестах (FastAPI dependency_overrides).
    return Settings()
