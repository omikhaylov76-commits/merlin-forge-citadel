"""Гвоздь на /readyz: при живой БД с миграциями на head — ready (200)."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_readyz_ready(_migrated):
    client = TestClient(create_app())
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
