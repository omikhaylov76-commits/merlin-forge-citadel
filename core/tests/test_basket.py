"""Гвозди на Набор Оператора (НАБОР-1, витрина+хранение): оператор добавляет сетап → readout →
dedup по (symbol,tf) upsert'ом (не дубль) → удаление; RBAC (клиент/портал 403, закон №5);
аудит add/remove (закон №4). Ничего не торгует. Нужен PG (миграции в _migrated)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import get_sessionmaker
from app.main import create_app


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        s.execute(text("DELETE FROM basket_items"))
        s.commit()


def _login(c: TestClient, email: str, pw: str) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_basket_add_list_dedup_remove(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")

    # старт: Набор пуст
    assert c.get("/v1/basket/items", headers=op).json() == []

    # звёздочка на сетапе → в Набор
    body = {
        "symbol": "ETHUSDT", "tf": "4h", "source": "scout",
        "context": {"score": 100, "stage": "Готов", "detector": "pifagor-v81"},
    }
    r = c.post("/v1/basket/items", headers=op, json=body)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["symbol"] == "ETHUSDT" and item["tf"] == "4h" and item["source"] == "scout"
    assert item["context"]["score"] == 100

    lst = c.get("/v1/basket/items", headers=op).json()
    assert len(lst) == 1

    # повторная звёздочка того же (symbol,tf) — UPSERT (не дубль), контекст обновляется
    body2 = {**body, "context": {"score": 88, "stage": "Отслеживаем"}}
    r2 = c.post("/v1/basket/items", headers=op, json=body2)
    assert r2.status_code == 201
    assert r2.json()["id"] == item["id"]  # тот же ряд, не новый
    lst2 = c.get("/v1/basket/items", headers=op).json()
    assert len(lst2) == 1
    assert lst2[0]["context"]["score"] == 88

    # другая монета — отдельный ряд
    c.post("/v1/basket/items", headers=op, json={
        "symbol": "BTCUSDT", "tf": "1h", "source": "screener", "context": {"impulse": 1.7},
    })
    assert len(c.get("/v1/basket/items", headers=op).json()) == 2

    # убрать ETHUSDT
    d = c.delete(f"/v1/basket/items/{item['id']}", headers=op)
    assert d.status_code == 204
    left = c.get("/v1/basket/items", headers=op).json()
    assert [x["symbol"] for x in left] == ["BTCUSDT"]

    # аудит: add + remove по нашему элементу записаны (закон №4)
    with get_sessionmaker()() as s:
        actions = {
            row[0]
            for row in s.execute(
                text("SELECT action FROM audit_log WHERE entity = :e"), {"e": item["id"]}
            ).all()
        }
    assert {"basket_item_added", "basket_item_removed"} <= actions


def test_basket_client_forbidden(clean, users):
    """Клиент (портал) прав на Набор не имеет — только оператор (закон №5)."""
    c = TestClient(create_app())
    cli = _login(c, "a@mfc.local", "a-pass")
    assert c.get("/v1/basket/items", headers=cli).status_code == 403
    r = c.post("/v1/basket/items", headers=cli, json={
        "symbol": "BTCUSDT", "tf": "4h", "source": "scout", "context": {},
    })
    assert r.status_code == 403


def test_basket_remove_missing_404(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    assert c.delete(f"/v1/basket/items/{uuid.uuid4()}", headers=op).status_code == 404


def test_basket_bad_source_422(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    r = c.post("/v1/basket/items", headers=op, json={
        "symbol": "ETHUSDT", "tf": "4h", "source": "manual", "context": {},
    })
    assert r.status_code == 422  # source ∉ {scout,screener}
