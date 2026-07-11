"""CoreClient (сторона картриджа): корректные запросы к API S4. Сеть — httpx.MockTransport."""

import json

import httpx

from app.client import CoreClient


class _Rec:
    def __init__(self, next_response=None):
        self.reqs: list[dict] = []
        self._next = next_response or {"cmd": "none", "cmd_id": None}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.reqs.append({
            "method": request.method,
            "path": request.url.path,
            "auth": request.headers.get("authorization"),
            "body": json.loads(request.content) if request.content else None,
        })
        if request.url.path.endswith("/commands/next"):
            return httpx.Response(200, json=self._next)
        return httpx.Response(200, json={"ok": True})


def _client(rec: _Rec) -> CoreClient:
    return CoreClient(
        base_url="http://core", token="tok",
        client=httpx.Client(transport=httpx.MockTransport(rec.handler)),
    )


def test_heartbeat_posts_expected():
    rec = _Rec()
    _client(rec).heartbeat(status="running", uptime_s=12.0, contract_version="v0")
    (r,) = rec.reqs
    assert r["method"] == "POST" and r["path"] == "/v1/telemetry/heartbeat"
    assert r["auth"] == "Bearer tok"
    assert r["body"] == {"status": "running", "uptime_s": 12.0, "contract_version": "v0"}


def test_push_equity_and_trades():
    rec = _Rec()
    c = _client(rec)
    c.push_equity({"ts": "t", "equity": 1.0, "currency": "USDT"})
    c.push_trades([{"ts": "t", "exec_id": "e1", "symbol": "X", "side": "buy", "qty": 1}])
    paths = [r["path"] for r in rec.reqs]
    assert paths == ["/v1/telemetry/equity", "/v1/telemetry/trades"]


def test_empty_batches_not_sent():
    rec = _Rec()
    c = _client(rec)
    c.push_trades([])
    c.push_events([])
    assert rec.reqs == []  # пустые батчи не шлём


def test_next_command_parses():
    rec = _Rec(next_response={"cmd": "pause", "cmd_id": "c1"})
    got = _client(rec).next_command(wait=0)
    assert got == {"cmd": "pause", "cmd_id": "c1"}
    assert rec.reqs[0]["method"] == "GET" and rec.reqs[0]["path"] == "/v1/commands/next"


def test_ack_command_posts_body():
    rec = _Rec()
    _client(rec).ack_command(cmd_id="c1", result="ok", detail={"x": 1})
    (r,) = rec.reqs
    assert r["path"] == "/v1/commands/c1/ack"
    assert r["body"] == {"result": "ok", "detail": {"x": 1}}
