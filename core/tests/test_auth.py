"""Гвозди auth (закон №8): логин→токен, revoke рвёт доступ, RBAC 403, владение 403, request-id."""

from fastapi.testclient import TestClient

from app.main import create_app


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_and_me(users):
    c = TestClient(create_app())
    r = c.get("/v1/auth/me", headers=_login(c, "op@mfc.local", "op-pass"))
    assert r.status_code == 200
    assert r.json()["role"] == "operator"


def test_bad_password_401(users):
    c = TestClient(create_app())
    r = c.post("/v1/auth/login", json={"email": "a@mfc.local", "password": "wrong"})
    assert r.status_code == 401


def test_no_token_401(users):
    assert TestClient(create_app()).get("/v1/auth/me").status_code == 401


def test_logout_revokes_access(users):
    c = TestClient(create_app())
    h = _login(c, "a@mfc.local", "a-pass")
    assert c.get("/v1/auth/me", headers=h).status_code == 200
    assert c.post("/v1/auth/logout", headers=h).status_code == 204
    assert c.get("/v1/auth/me", headers=h).status_code == 401  # отзыв мгновенный


def test_rbac_admin_only(users):
    c = TestClient(create_app())
    assert c.get("/v1/admin/ping", headers=_login(c, "op@mfc.local", "op-pass")).status_code == 200
    assert c.get("/v1/admin/ping", headers=_login(c, "a@mfc.local", "a-pass")).status_code == 403


def test_ownership_self_vs_other(users):
    c = TestClient(create_app())
    a_id, b_id = str(users["a"].id), str(users["b"].id)
    ha = _login(c, "a@mfc.local", "a-pass")
    assert c.get(f"/v1/users/{a_id}", headers=ha).status_code == 200  # свой профиль
    assert c.get(f"/v1/users/{b_id}", headers=ha).status_code == 403  # чужой → 403
    hop = _login(c, "op@mfc.local", "op-pass")
    assert c.get(f"/v1/users/{b_id}", headers=hop).status_code == 200  # оператор видит любого


def test_request_id_header(users):
    r = TestClient(create_app()).get("/healthz")
    assert r.headers.get("x-request-id")
