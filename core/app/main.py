"""App-factory ядра.

Почему фабрика, а не глобальный app: тесты поднимают чистый экземпляр с инжектированным
конфигом, без скрытого глобального состояния. uvicorn использует модульный `app` ниже.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.logging import setup_logging
from app.readiness import is_ready


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="Merlin Forge Citadel — core", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        # Liveness: «процесс жив», без обращения к БД. Dead-man тик алертов (SCL3) — в MFC-002.
        return {"status": "ok", "service": "core", "env": settings.env}

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        # Readiness: БД доступна И миграции на head. 503, если не готов (Railway не льёт трафик).
        if is_ready():
            return JSONResponse({"status": "ready", "service": "core"})
        return JSONResponse({"status": "not_ready", "service": "core"}, status_code=503)

    return app


app = create_app()  # точка входа uvicorn: app.main:app
