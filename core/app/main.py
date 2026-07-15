"""App-factory ядра.

Почему фабрика, а не глобальный app: тесты поднимают чистый экземпляр с инжектированным
конфигом, без скрытого глобального состояния. uvicorn использует модульный `app` ниже.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.context import set_request_id
from app.db import get_sessionmaker
from app.instance_health import scan_once
from app.logging import setup_logging
from app.periods import generate_periods_once
from app.readiness import is_ready
from app.routes import router
from app.routes_billing import router as billing_router
from app.routes_commands import router as commands_router
from app.routes_crm import router as crm_router
from app.routes_fleet import router as fleet_router
from app.routes_internal import router as internal_router
from app.routes_telemetry import router as telemetry_router
from app.scheduler import Scheduler


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    # «Часовой» создаётся здесь (живёт на app.state — без скрытого глобального состояния,
    # см. докстринг фабрики), а стартует/гасится в lifespan. /healthz видит его всегда, даже
    # без поднятого lifespan (bare TestClient): тогда state=stopped, а liveness = ok.
    scheduler = Scheduler(tick_seconds=settings.scheduler_tick_seconds)
    # Первая боевая свёртка (MFC-003): stale-скан health инстансов по свежести heartbeat.
    # to_thread внутри часового → короткая БД-сессия не блокирует цикл (SCL1).
    scheduler.register(
        "instance-health-scan",
        interval_s=0.0,  # каждый оборот часового (в проде тик 60с)
        fn=lambda: scan_once(
            get_sessionmaker(),
            settings.instance_stale_after_seconds,
            settings.instance_dead_after_seconds,
        ),
    )
    # Генератор периодов (MFC-F3-3): на смене месяца заводит следующий период активным счетам.
    scheduler.register(
        "billing-period-generator",
        interval_s=settings.billing_generator_interval_seconds,
        fn=lambda: generate_periods_once(get_sessionmaker()),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # start() внутри try: если он частично упадёт, finally-stop() приберёт (stop без
        # старта безопасен). Аргумент — app от FastAPI, здесь не нужен.
        try:
            await scheduler.start()
            yield
        finally:
            await scheduler.stop()

    # Доки закрыты по умолчанию (#18.3): на публичном ядре /docs, /redoc, /openapi.json не
    # отдаём — иначе карта API уходит в интернет. ENABLE_DOCS=1 включает их для локали.
    doc_urls = (
        {}
        if settings.enable_docs
        else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    )
    app = FastAPI(
        title="Merlin Forge Citadel — core", version="0.1.0", lifespan=lifespan, **doc_urls
    )
    app.state.scheduler = scheduler

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        # request-id на каждый запрос → в логи и заголовок ответа (сшивка с audit_log)
        rid = set_request_id(request.headers.get("X-Request-ID"))
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    app.include_router(router)
    app.include_router(internal_router)  # internal jobs API (шов S3, ADR-0009)
    app.include_router(telemetry_router)  # приём телеметрии бота (шов S4, Контракт v0)
    app.include_router(commands_router)  # команды боту (шов S4←, ADR-0005)
    app.include_router(crm_router)  # CRM-API оператора (Ф3): clients/exchange_accounts/contracts
    app.include_router(billing_router)  # биллинг-lifecycle счёта (Ф3): активация/терминация
    app.include_router(fleet_router)  # агрегаты флота (Ф4): Обзор консоли (readout)

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
