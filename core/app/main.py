"""App-factory ядра.

Почему фабрика, а не глобальный app: тесты поднимают чистый экземпляр с инжектированным
конфигом, без скрытого глобального состояния. uvicorn использует модульный `app` ниже.
"""

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="Merlin Forge Citadel — core", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Liveness для Railway/uptime-пинга. Без обращения к БД: liveness ≠ readiness.
        # Dead-man тик диспетчера алертов (SCL3) прицепится сюда в MFC-002.
        return {"status": "ok", "service": "core", "env": settings.env}

    return app


app = create_app()  # точка входа uvicorn: app.main:app
