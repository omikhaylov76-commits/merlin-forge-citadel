"""App-factory ядра.

Почему фабрика, а не глобальный app: тесты поднимают чистый экземпляр с инжектированным
конфигом, без скрытого глобального состояния. uvicorn использует модульный `app` ниже.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.context import set_request_id
from app.logging import setup_logging
from app.readiness import is_ready
from app.routes import router
from app.scheduler import Scheduler


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    # «Часовой» создаётся здесь (живёт на app.state — без скрытого глобального состояния,
    # см. докстринг фабрики), а стартует/гасится в lifespan. /healthz видит его всегда, даже
    # без поднятого lifespan (bare TestClient): тогда state=stopped, а liveness = ok.
    scheduler = Scheduler(tick_seconds=settings.scheduler_tick_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()

    app = FastAPI(title="Merlin Forge Citadel — core", version="0.1.0", lifespan=lifespan)
    app.state.scheduler = scheduler

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        # request-id на каждый запрос → в логи и заголовок ответа (сшивка с audit_log)
        rid = set_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(router)

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        # Liveness: «процесс жив», без БД. Верхний status всегда ok (вариант A, ADR-0012);
        # свежесть цикла-часового — в блоке scheduler (dead-man тик, SCL3, seams.md:78).
        return {
            "status": "ok",
            "service": "core",
            "env": settings.env,
            "scheduler": scheduler.health(),
        }

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        # Readiness: БД доступна И миграции на head. 503, если не готов (Railway не льёт трафик).
        if is_ready():
            return JSONResponse({"status": "ready", "service": "core"})
        return JSONResponse({"status": "not_ready", "service": "core"}, status_code=503)

    return app


app = create_app()  # точка входа uvicorn: app.main:app
