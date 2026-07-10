# orchestrator — руки платформы
Слушает jobs ядра (deploy/stop), управляет контейнерами через InfraDriver.
v1: RailwayDriver (GraphQL: serviceCreate(image, variables), redeploy, delete). Позже: DockerDriver.
Единственный компонент с master-key секретов (ADR-0004). Не знает: UI, биллинг, домен целиком.
