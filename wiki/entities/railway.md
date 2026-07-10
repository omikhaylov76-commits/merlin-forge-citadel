---
type: entity
title: Railway
tags: [infra, v1]
updated: 2026-07-10
---
Хостинг v1 (Оператор уже живёт здесь). Факты (проверено 2026-07): GraphQL API умеет
serviceCreate из Docker-образа + variables / redeploy / delete → оркестрация возможна.
Static outbound IP: только Pro ($20/мес), IP ОБЩИЕ (шарятся) — риск принят в ADR-0003.
Цены: RAM $10/ГБ/мес, CPU $20/vCPU/мес; флот ~12 ботов ≈ $70–110/мес. Переход на Pro —
на Фазе 1–2, не раньше. План Б: DockerDriver + VPS (труба в оркестраторе).
