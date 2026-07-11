"""CoreClient (шов S3): разбор 200/204 у lease_next и корректное тело ack. Сеть — MockTransport."""

import json

import httpx

from app.core_client import CoreClient


def _client(handler) -> CoreClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return CoreClient(base_url="http://core", token="orch-tok", client=http)


def test_lease_next_parses_200():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/internal/jobs/next"
        assert request.headers["authorization"] == "Bearer orch-tok"
        return httpx.Response(200, json={
            "id": "job-1", "kind": "deploy", "instance_id": "inst-1",
            "payload": {"image": "paper:v0"}, "lease_nonce": "nonce-1",
        })

    lease = _client(handler).lease_next(wait=0)
    assert lease is not None
    assert (lease.id, lease.kind, lease.lease_nonce) == ("job-1", "deploy", "nonce-1")
    assert lease.payload["image"] == "paper:v0"


def test_lease_next_204_is_none():
    lease = _client(lambda r: httpx.Response(204)).lease_next(wait=0)
    assert lease is None


def test_ack_sends_expected_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/internal/jobs/job-1/ack"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "job-1", "status": "done"})

    _client(handler).ack(
        job_id="job-1", lease_nonce="nonce-1", result="done", detail={"infra_ref": "railway:p:s"}
    )
    assert seen["lease_nonce"] == "nonce-1"
    assert seen["result"] == "done"
    assert seen["detail"] == {"infra_ref": "railway:p:s"}
    assert seen["terminal"] is False
