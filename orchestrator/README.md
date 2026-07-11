# orchestrator — руки платформы
Арендует jobs через internal API ядра (long-poll, ADR-0009; таблицу напрямую НЕ читает, закон №3),
управляет контейнерами через InfraDriver. Единственный держатель приватной половины master-пары
(ADR-0004/0010). Не знает: UI, биллинг, домен целиком.

## Структура (MFC-004)
- `app/core_client.py` — клиент шва S3: `lease_next` (204→None), `ack` (done|failed|release, fencing-nonce).
- `app/worker.py` — цикл: аренда → диспетч по kind → исполнение через InfraDriver → ack. Отказы:
  InfraError→release (без штрафа attempts, OPS16), неустранимое→failed+terminal, недоступное ядро→backoff.
- `app/infra/` — шов S5: `base.InfraDriver` (ABC) · `fake.FakeDriver` (in-memory, тесты/сквозняк) ·
  `railway.RailwayDriver` (GraphQL, ⚠️ схема — на боевой обкатке) · `docker.DockerDriver` (шумная заглушка, план Б).
- `app/main.py` — конфиг → фабрика драйвера (fake|railway|docker) → CoreClient → цикл (мягкий stop по сигналу).

## Запуск / тесты
`pip install -e ".[dev]"` в `orchestrator/`. Тесты БД не требуют (FakeDriver + httpx.MockTransport):
`PYTHONPATH="$PWD" pytest -q`. Боевой запуск: env `CORE_API_URL`, `ORCHESTRATOR_TOKEN`, `DRIVER`,
для Railway — `RAILWAY_API_TOKEN`/`RAILWAY_PROJECT_ID`; `python -m app.main`.
⚠️ Боевая обкатка Railway API — отдельная веха roadmap (проверка допущения №3); в CI Railway не трогаем.
