"""Гвоздь на /healthz: liveness отвечает 200, не трогает БД, показывает блок часового."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "core"
    # Блок часового присутствует; без поднятого lifespan цикл не запущен → stopped (liveness ok).
    assert body["scheduler"]["state"] == "stopped"


def test_healthz_scheduler_running_under_lifespan() -> None:
    # С поднятым lifespan (context manager) startup запускает часового → state=running.
    with TestClient(create_app()) as client:
        body = client.get("/healthz").json()
    assert body["status"] == "ok"                      # вариант A: верхний status не гейтит
    assert body["scheduler"]["state"] == "running"
    assert body["scheduler"]["tick_age_s"] is not None
