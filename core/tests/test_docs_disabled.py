"""Гвоздь на закрытые доки (#18.3): публичное ядро не отдаёт карту API наружу.

По умолчанию /docs, /redoc, /openapi.json → 404. Под ENABLE_DOCS=1 (локаль) — открыты.
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


def test_docs_closed_by_default() -> None:
    # Дефолт (enable_docs=False) = прод: доков нет, карта API не палится.
    client = TestClient(create_app(Settings(enable_docs=False)))
    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path


def test_docs_open_under_flag() -> None:
    # ENABLE_DOCS=1 для локали → доки доступны (Swagger 200, схема отдаётся).
    client = TestClient(create_app(Settings(enable_docs=True)))
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path
