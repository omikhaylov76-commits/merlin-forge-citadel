# orchestrator — руки платформы
Арендует jobs через internal API ядра (long-poll, ADR-0009; таблицу напрямую НЕ читает),
управляет контейнерами через InfraDriver.
v1: RailwayDriver (GraphQL: serviceCreate(image, variables), redeploy, delete). Позже: DockerDriver.
Единственный держатель приватной половины master-пары (ADR-0004/0010). Не знает: UI, биллинг, домен целиком.
