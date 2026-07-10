"""Гвоздь на /healthz: liveness отвечает 200 и не трогает БД."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "core"
