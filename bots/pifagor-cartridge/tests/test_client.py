"""CoreClient: корректные запросы + ОБЯЗАТЕЛЬНАЯ классификация 4xx/5xx (гейт Ф2, Куратор #6/#7).

Сеть — httpx.MockTransport. Проверяем: транзиентное vs перманентное vs 413, backoff ретраит только
транзиентное и уважает исчерпание, перманентное поднимается сразу.
"""

import json

import httpx
import pytest

from app.client import (
    CoreClient,
    PayloadTooLarge,
    PermanentError,
    TransientError,
    classify_status,
    send_with_backoff,
)


class _Rec:
    def __init__(self, status=200, body=None, next_response=None):
        self.reqs: list[dict] = []
        self._status = status
        self._body = body if body is not None else {"ok": True}
        self._next = next_response or {"cmd": "none", "cmd_id": None}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.reqs.append({
            "method": request.method, "path": request.url.path,
            "auth": request.headers.get("authorization"),
            "body": json.loads(request.content) if request.content else None,
        })
        if request.url.path.endswith("/commands/next"):
            return httpx.Response(200, json=self._next)
        return httpx.Response(self._status, json=self._body)


def _client(rec: _Rec) -> CoreClient:
    return CoreClient(base_url="http://core", token="tok",
                      client=httpx.Client(transport=httpx.MockTransport(rec.handler)))


# ── корректные запросы (как эталон) ──────────────────────────────────────────

def test_heartbeat_posts_expected():
    rec = _Rec()
    _client(rec).heartbeat(status="running", uptime_s=12.0, contract_version="v0")
    (r,) = rec.reqs
    assert r["method"] == "POST" and r["path"] == "/v1/telemetry/heartbeat"
    assert r["auth"] == "Bearer tok"
    assert r["body"] == {"status": "running", "uptime_s": 12.0, "contract_version": "v0"}


def test_empty_batches_not_sent():
    rec = _Rec()
    c = _client(rec)
    c.push_trades([])
    c.push_events([])
    assert rec.reqs == []


def test_next_command_and_ack():
    rec = _Rec(next_response={"cmd": "pause", "cmd_id": "c1"})
    c = _client(rec)
    assert c.next_command(wait=0) == {"cmd": "pause", "cmd_id": "c1"}
    c.ack_command(cmd_id="c1", result="ok", detail={"x": 1})
    assert rec.reqs[-1]["path"] == "/v1/commands/c1/ack"
    assert rec.reqs[-1]["body"] == {"result": "ok", "detail": {"x": 1}}


# ── классификация статусов (единый источник) ─────────────────────────────────

@pytest.mark.parametrize("status,kind", [
    (200, "ok"), (201, "ok"), (204, "ok"),
    (400, "permanent"), (401, "permanent"), (403, "permanent"), (404, "permanent"),
    (409, "permanent"), (422, "permanent"),
    (408, "transient"), (425, "transient"), (429, "transient"),
    (413, "too_large"),
    (500, "transient"), (502, "transient"), (503, "transient"), (504, "transient"),
])
def test_classify_status_table(status, kind):
    assert classify_status(status) == kind


@pytest.mark.parametrize("status,exc", [
    (401, PermanentError), (422, PermanentError), (404, PermanentError),
    (429, TransientError), (408, TransientError), (503, TransientError), (500, TransientError),
    (413, PayloadTooLarge),
])
def test_post_raises_typed_error(status, exc):
    rec = _Rec(status=status)
    with pytest.raises(exc):
        _client(rec).push_equity({"ts": "t", "equity": 1.0, "currency": "USDT"})


def test_network_error_is_transient():
    def boom(_request):
        raise httpx.ConnectError("refused")
    c = CoreClient(base_url="http://core", token="t",
                   client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(TransientError):
        c.heartbeat(status="running", uptime_s=1.0, contract_version="v0")


def test_permanent_error_carries_status_but_not_body():
    rec = _Rec(status=401, body={"secret": "leak"})
    try:
        _client(rec).push_equity({"ts": "t", "equity": 1.0, "currency": "USDT"})
    except PermanentError as e:
        assert e.status == 401
        assert "leak" not in str(e)      # закон №2: тело/токен в текст ошибки не течёт
    else:
        pytest.fail("ожидался PermanentError")


# ── send_with_backoff ────────────────────────────────────────────────────────

def test_backoff_retries_transient_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("5xx", status=503)

    send_with_backoff(fn, retries=3, base_s=1.0, cap_s=10.0, sleep=slept.append)
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]            # экспонента: base*2^0, base*2^1


def test_backoff_reraises_after_exhaustion():
    slept: list[float] = []

    def always_transient():
        raise TransientError("down", status=503)

    with pytest.raises(TransientError):
        send_with_backoff(always_transient, retries=2, base_s=1.0, cap_s=1.0, sleep=slept.append)
    assert slept == [1.0, 1.0]           # cap уважается (min(cap, base*2^n))


def test_backoff_does_not_retry_permanent():
    calls = {"n": 0}

    def perm():
        calls["n"] += 1
        raise PermanentError("422", status=422)

    with pytest.raises(PermanentError):
        send_with_backoff(perm, retries=5, base_s=1.0, cap_s=1.0, sleep=lambda _s: None)
    assert calls["n"] == 1               # перманентное не ретраится
