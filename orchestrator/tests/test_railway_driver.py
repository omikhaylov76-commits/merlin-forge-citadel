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


def _handler(
    existing_names=(),
    record=None,
    gql_error=False,
    http_status=200,
    env_edges=({"node": {"id": "env-prod", "name": "production"}},),
):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        if record is not None:
            record.append(
                {
                    "query": query,
                    "auth": request.headers.get("authorization"),
                    "vars": body.get("variables", {}),
                }
            )
        if http_status != 200:
            return httpx.Response(http_status, json={})
        if gql_error:
            return httpx.Response(200, json={"errors": [{"message": "boom"}]})
        if query.startswith("query FindService"):
            edges = [{"node": {"id": f"id-{n}", "name": n}} for n in existing_names]
            return httpx.Response(200, json={"data": {"project": {"services": {"edges": edges}}}})
        if query.startswith("query Environments"):
            return httpx.Response(
                200, json={"data": {"project": {"environments": {"edges": list(env_edges)}}}}
            )
        if "serviceCreate" in query:
            return httpx.Response(200, json={"data": {"serviceCreate": {"id": "id-new"}}})
        if "serviceInstanceDeploy" in query:
            return httpx.Response(200, json={"data": {"serviceInstanceDeploy": True}})
        if "serviceDelete" in query:
            return httpx.Response(200, json={"data": {"serviceDelete": True}})
        return httpx.Response(200, json={"data": {}})

    return handler


def _driver(handler, **kw) -> RailwayDriver:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RailwayDriver(api_token="tok", project_id="proj-1", client=client, **kw)


def _sent(record) -> str:
    return " ".join(r["query"] for r in record)


def _call(record, needle: str) -> dict:
    return next(r for r in record if needle in r["query"])


def test_deploy_creates_when_absent():
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec))
    ref = d.deploy(_spec())
    assert ref == "railway:proj-1:mfc-inst-abc"              # ref детерминирован от имени
    assert "serviceCreate" in _sent(rec)                     # отсутствовал → создали
    assert all(r["auth"] == "Bearer tok" for r in rec)       # токен в каждом запросе


def test_deploy_adopts_when_present():
    rec: list = []
    d = _driver(_handler(existing_names=("mfc-inst-abc",), record=rec))
    d.deploy(_spec())
    assert "serviceCreate" not in _sent(rec)  # уже есть → усыновили, дубль не создаём (OPS2)


def test_deploy_launches_image_after_create():
    # serviceCreate не запускает контейнер — образ деплоится serviceInstanceDeploy (пробел с.5).
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec))
    d.deploy(_spec())
    assert "serviceInstanceDeploy" in _sent(rec)
    assert _call(rec, "serviceInstanceDeploy")["vars"]["environmentId"] == "env-prod"


def test_deploy_launches_image_on_adopt():
    # усыновлённый сервис тоже (пере)деплоим — иначе новый образ не подхватится.
    rec: list = []
    d = _driver(_handler(existing_names=("mfc-inst-abc",), record=rec))
    d.deploy(_spec())
    assert "serviceInstanceDeploy" in _sent(rec)


def test_registry_credentials_sent_when_configured():
    # ПРИВАТНЫЙ образ (ghcr): креды идут в serviceCreate.
    rec: list = []
    d = _driver(
        _handler(existing_names=(), record=rec),
        registry_username="ghuser",
        registry_token="ghp_secret",
    )
    d.deploy(_spec())
    creds = _call(rec, "serviceCreate")["vars"]["input"].get("registryCredentials")
    assert creds == {"username": "ghuser", "password": "ghp_secret"}


def test_no_registry_credentials_when_absent():
    # Публичный образ (paper-bot): ключ не шлём — обратная совместимость.
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec))
    d.deploy(_spec())
    assert "registryCredentials" not in _call(rec, "serviceCreate")["vars"]["input"]


def test_deploy_env_extra_injected():
    # demo-ключи из конфига оркестратора вливаются в env деплоя (картридж бутится, #16).
    rec: list = []
    d = _driver(
        _handler(existing_names=(), record=rec),
        deploy_env_extra={"BYBIT_API_KEY": "k", "BYBIT_API_SECRET": "s"},
    )
    d.deploy(_spec())
    v = _call(rec, "serviceCreate")["vars"]["input"]["variables"]
    assert v["BYBIT_API_KEY"] == "k" and v["BYBIT_API_SECRET"] == "s"  # вливка есть
    assert v["MFC_INSTANCE_ID"] == "abc"  # spec.env (из payload) сохранён


def test_deploy_spec_env_overrides_extra():
    # per-instance env (из payload ядра) перекрывает общую вливку — приоритет spec.env.
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec), deploy_env_extra={"MFC_INSTANCE_ID": "G"})
    d.deploy(_spec())  # spec env MFC_INSTANCE_ID=abc
    assert _call(rec, "serviceCreate")["vars"]["input"]["variables"]["MFC_INSTANCE_ID"] == "abc"


def test_environment_id_from_config_skips_lookup():
    # environmentId задан в конфиге → драйвер не тратит запрос на поиск окружения.
    rec: list = []
    d = _driver(_handler(existing_names=(), record=rec), environment_id="env-fixed")
    d.deploy(_spec())
    assert "query Environments" not in _sent(rec)
    assert _call(rec, "serviceInstanceDeploy")["vars"]["environmentId"] == "env-fixed"


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
