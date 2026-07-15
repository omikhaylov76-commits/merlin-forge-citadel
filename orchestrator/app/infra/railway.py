"""RailwayDriver — InfraDriver поверх Railway GraphQL API v2 (ADR-0003, entity railway).

✅ СХЕМА ПОДТВЕРЖДЕНА НА ЖИВОМ RAILWAY (обкатка 2026-07-11): FindService (project.services.edges),
serviceCreate (ServiceCreateInput), serviceDelete и формат infra_ref прошли против реального API —
полный цикл deploy→status→destroy отработал. Маппинг deployment-статуса — по мере надобности.

Деплой картриджа в облако (#46): serviceCreate САМ образ не запускает — после него зовём
serviceInstanceDeploy(serviceId, environmentId). Для ПРИВАТНОГО ghcr-образа кладём
registryCredentials (username+PAT read:packages) прямо в serviceCreate — креды живут в env
оркестратора, не в git/лог (закон №2).

Идемпотентность по имени (S3/S5, OPS2): сервис зовётся mfc-inst-{id} (ядро задаёт детерминированно);
перед созданием ищем его в проекте — «усынови или создай», дубль после create удаляем.
Секретов биржи в v1 нет (paper-bot; конверт-шифрование — Ф2).

Сетевой слой — httpx с trust_env=False: обкатка показала, что с trust_env=True клиент ВИСНЕТ на
некоторых окружениях (netrc/CA/proxy из env); прямой вызов API прокси не требует.
"""

from __future__ import annotations

import httpx

from app.infra.base import DeploySpec, InfraDriver, InfraError, InfraStatus, make_ref, parse_ref

# GraphQL-операции. ⚠️ Формы — по публичной схеме Railway v2 (entity railway); финальные имена
# полей и обязательные аргументы (environmentId и т.п.) фиксируются на живой обкатке.
_Q_FIND_SERVICE = """
query FindService($projectId: String!) {
  project(id: $projectId) { services { edges { node { id name } } } }
}
""".strip()

_M_CREATE_SERVICE = """
mutation CreateService($input: ServiceCreateInput!) {
  serviceCreate(input: $input) { id name }
}
""".strip()

_M_DELETE_SERVICE = """
mutation DeleteService($id: String!) {
  serviceDelete(id: $id)
}
""".strip()

# Запуск образа: serviceCreate только создаёт сервис, деплой контейнера — отдельным вызовом
# (пробел драйвера с.5). environmentId обязателен — резолвим в _environment_id().
_M_DEPLOY_INSTANCE = """
mutation DeployInstance($serviceId: String!, $environmentId: String!) {
  serviceInstanceDeploy(serviceId: $serviceId, environmentId: $environmentId)
}
""".strip()

# Список окружений проекта → id (предпочитаем production). Нужен для serviceInstanceDeploy.
_Q_ENVIRONMENTS = """
query Environments($projectId: String!) {
  project(id: $projectId) { environments { edges { node { id name } } } }
}
""".strip()


class RailwayDriver(InfraDriver):
    def __init__(
        self,
        *,
        api_token: str,
        project_id: str,
        api_url: str = "https://backboard.railway.app/graphql/v2",
        environment_id: str = "",
        registry_username: str = "",
        registry_token: str = "",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = api_token
        self._project = project_id
        self._url = api_url
        # Окружение для serviceInstanceDeploy: если пусто — определим по проекту (production).
        self._env_id = environment_id
        # registry-креды для ПРИВАТНОГО образа (ghcr): в env оркестратора, не в git/лог (закон №2).
        self._registry_username = registry_username
        self._registry_token = registry_token
        # Инъекция клиента — точка подмены в тестах (MockTransport); иначе — реальный httpx.
        # trust_env=False: обкатка показала зависание клиента при чтении netrc/CA/proxy из env;
        # прямому вызову Railway API прокси не нужен (без этого POST висел мимо своего таймаута).
        self._client = client or httpx.Client(timeout=timeout, trust_env=False)

    def _gql(self, query: str, variables: dict) -> dict:
        """Один GraphQL-вызов. Сеть/HTTP/GraphQL-ошибки → InfraError (backoff+release)."""
        try:
            resp = self._client.post(
                self._url,
                json={"query": query, "variables": variables},
                headers={"Authorization": f"Bearer {self._token}"},
            )
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:  # сеть, не-2xx, битый JSON
            raise InfraError(f"Railway API недоступен: {exc}") from exc
        if body.get("errors"):
            raise InfraError(f"Railway GraphQL errors: {body['errors']}")
        return body.get("data") or {}

    def _find_service_id(self, name: str) -> str | None:
        """Найти сервис по имени в проекте → serviceId или None. Основа усыновления (OPS2)."""
        data = self._gql(_Q_FIND_SERVICE, {"projectId": self._project})
        edges = (((data.get("project") or {}).get("services") or {}).get("edges")) or []
        for edge in edges:
            node = edge.get("node") or {}
            if node.get("name") == name:
                return node.get("id")
        return None

    def deploy(self, spec: DeploySpec) -> str:
        # Усынови-или-создай по детерминированному имени (дубль недопустим, OPS2).
        existing = self._find_service_id(spec.name)
        if existing is None:
            create_input = {
                "projectId": self._project,
                "name": spec.name,
                "source": {"image": spec.image},
                "variables": spec.env,
            }
            # ПРИВАТНЫЙ образ (ghcr): registry-креды прямо в serviceCreate.
            # Пусто → образ считаем публичным, ключ не шлём (обратная совместимость paper-bot).
            if self._registry_token:
                create_input["registryCredentials"] = {
                    "username": self._registry_username,
                    "password": self._registry_token,
                }
            data = self._gql(_M_CREATE_SERVICE, {"input": create_input})
            service_id = (data.get("serviceCreate") or {}).get("id")
        else:
            # Сервис уже есть — усыновляем (variableUpsert существующего — при нужде, QUEUE).
            service_id = existing
        # Запустить образ: serviceCreate сам по себе контейнер НЕ деплоит (пробел драйвера с.5).
        env_id = self._environment_id()
        if service_id and env_id:
            self._gql(
                _M_DEPLOY_INSTANCE,
                {"serviceId": service_id, "environmentId": env_id},
            )
        return make_ref(self._project, spec.name)

    def _environment_id(self) -> str | None:
        """environmentId для serviceInstanceDeploy: из конфига или найденный по проекту."""
        if self._env_id:
            return self._env_id
        data = self._gql(_Q_ENVIRONMENTS, {"projectId": self._project})
        edges = (((data.get("project") or {}).get("environments") or {}).get("edges")) or []
        chosen = None
        for edge in edges:
            node = edge.get("node") or {}
            if node.get("name") == "production":  # мульти-env: предпочитаем production
                chosen = node.get("id")
                break
        if chosen is None and edges:  # иначе первое доступное
            chosen = (edges[0].get("node") or {}).get("id")
        self._env_id = chosen or ""  # кэш (в т.ч. пустой — не долбим API повторно)
        return self._env_id or None

    def destroy(self, infra_ref: str) -> None:
        _, _, name = parse_ref(infra_ref)
        service_id = self._find_service_id(name)
        if service_id is None:
            return  # сервиса нет — идемпотентный успех (OPS5)
        self._gql(_M_DELETE_SERVICE, {"id": service_id})

    def status(self, infra_ref: str) -> str:
        _, _, name = parse_ref(infra_ref)
        # ⚠️ детальный маппинг deployment-статуса — на обкатке; v1: есть сервис → RUNNING.
        return InfraStatus.RUNNING if self._find_service_id(name) else InfraStatus.ABSENT
