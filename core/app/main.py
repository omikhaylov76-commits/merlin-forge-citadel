"""App-factory ядра.

Почему фабрика, а не глобальный app: тесты поднимают чистый экземпляр с инжектированным
конфигом, без скрытого глобального состояния. uvicorn использует модульный `app` ниже.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.context import set_request_id
from app.logging import setup_logging
from app.readiness import is_ready
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="Merlin Forge Citadel — core", version="0.1.0")

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        # request-id на каждый запрос → в логи и заголовок ответа (сшивка с audit_log)
        rid = set_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(router)

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
