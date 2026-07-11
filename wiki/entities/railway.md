---
type: entity
title: Railway
tags: [infra, v1]
updated: 2026-07-11
---
Хостинг v1 (Оператор уже живёт здесь). Факты (проверено 2026-07): GraphQL API умеет
serviceCreate из Docker-образа + variables / redeploy / delete → оркестрация возможна.
Static outbound IP: только Pro ($20/мес), IP ОБЩИЕ (шарятся) — риск принят в ADR-0003.
Цены: RAM $10/ГБ/мес, CPU $20/vCPU/мес; флот ~12 ботов ≈ $70–110/мес. Переход на Pro —
на Фазе 1–2, не раньше. План Б: DockerDriver + VPS (труба в оркестраторе).

✅ **Обкатка 2026-07-11 (живой Railway CLI + API):** (1) CLI собрал наш Dockerfile картриджа и
запустил процесс (deployability). (2) `RailwayDriver` (GraphQL API v2, `backboard.railway.app/graphql/v2`)
подтверждён на реальном API: полный цикл `FindService`(project.services.edges) → `serviceCreate`
(ServiceCreateInput) → status → `serviceDelete` отработал. Формат infra_ref `railway:{project}:{svc}` — ок.
Нюанс: httpx-клиент драйвера обязан быть с `trust_env=False` (иначе виснет на netrc/CA из env). Оба
тестовых проекта удалены после прогона. Квоты (сервисов/проект, rate-limit) — измерить при росте флота.
