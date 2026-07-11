"""RailwayDriver: HTTP-механика и логика усынови-или-создай / идемпотентный destroy / разбор ошибок.

Живой Railway НЕ трогаем (боевой прогон — отдельная веха): подменяем сеть httpx.MockTransport и
проверяем, ЧТО и КУДА драйвер шлёт, как ветвится и как превращает ошибки в InfraError.
"""

import json

import httpx
import pytest

from app.infra.base import DeploySpec, InfraError, InfraStatus
from app.infra.railway import RailwayDriver


def _spec(name="mfc-inst-abc") -> DeploySpec:
    return DeploySpec(image="paper-bot:v0", name=name, env={"MFC_INSTANCE_ID": "abc"})


def _handler(existing_names=(), record=None, gql_error=False, http_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        if record is not None:
            record.append((query, request.headers.get("authorization")))
        if http_status != 200:
            return httpx.Response(http_status, json={})
        if gql_error:
            return httpx.Response(200, json={"errors": [{"message": "boom"}]})
        if query.startswith("query FindService"):
            edges = [{"node": {"id": f"id-{n}", "name": n}} for n in existing_names]
            return httpx.Response(200, json={"data": {"project": {"services": {"edges": edges}}}})
        if "serviceCreate" in query:
            return httpx.Response(200, json={"data": {"serviceCreate": {"id": "id-new"}}})
        if "serviceDelete" in query:
            return httpx.Response(200, json={"data": {"serviceDelete": True}})
        return httpx.Response(200, json={"data": {}})

    return handler


def _driver(handler) -> RailwayDriver:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RailwayDriver(api_token="tok", project_id="proj-1", client=client)


def _sent(record) -> str:
    return " ".join(q for q, _ in record)


def test_deploy_creates_when_absent():
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec))
    ref = d.deploy(_spec())
    assert ref == "railway:proj-1:mfc-inst-abc"          # ref детерминирован от имени
    assert "serviceCreate" in _sent(rec)                 # отсутствовал → создали
    assert all(auth == "Bearer tok" for _, auth in rec)  # токен в каждом запросе


def test_deploy_adopts_when_present():
    rec: list = []
    d = _driver(_handler(existing_names=("mfc-inst-abc",), record=rec))
    d.deploy(_spec())
    assert "serviceCreate" not in _sent(rec)  # уже есть → усыновили, дубль не создаём (OPS2)


def test_destroy_absent_is_noop():
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec))
    d.destroy("railway:proj-1:mfc-inst-abc")
    assert "serviceDelete" not in _sent(rec)  # нет сервиса → идемпотентный успех (OPS5)


def test_destroy_present_deletes():
    rec: list = []
    d = _driver(_handler(existing_names=("mfc-inst-abc",), record=rec))
    d.destroy("railway:proj-1:mfc-inst-abc")
    assert "serviceDelete" in _sent(rec)


def test_status_running_vs_absent():
    running = _driver(_handler(existing_names=("mfc-inst-abc",)))
    absent = _driver(_handler(existing_names=()))
    assert running.status("railway:proj-1:mfc-inst-abc") == InfraStatus.RUNNING
    assert absent.status("railway:proj-1:mfc-inst-abc") == InfraStatus.ABSENT


def test_gql_errors_become_infraerror():
    d = _driver(_handler(gql_error=True))
    with pytest.raises(InfraError):
        d.deploy(_spec())


def test_http_error_becomes_infraerror():
    d = _driver(_handler(http_status=500))
    with pytest.raises(InfraError):
        d.deploy(_spec())
