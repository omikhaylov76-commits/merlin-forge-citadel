---
type: progress
title: Ф3 — видимость застрявшего биллинга (audit пропусков генератора)
tags: [f3, billing, audit, observability]
updated: 2026-07-15
---
# MFC-F3-4 · Видимость застрявшего биллинга (остаточный 🟢 #1 из DIRECTIVES #32)

**Цель:** тихие пропуски генератора периодов (нет equity / нет signed-договора / смена валюты)
сделать видимыми — audit-событие `period_generation_skipped(reason)` + readout «застрявших счетов».
Куратор (#32): «для денег операционная видимость обязательна (Оператор/Кавалл должны видеть
застрявший биллинг)». Это observability (не money-math) → само-ревью ок (#29).

**Что трогаем:**
- `core/app/periods.py` — единый `_blocked_reason` (решение о пропуске), дедуп-аудит `_record_skip`,
  readout `stuck_billing_accounts`. Математику периодов НЕ меняем.
- `core/app/routes_billing.py` — `GET /v1/billing/stuck-accounts` (operator RBAC, read-only).
- `core/tests/test_periods.py` — тесты: readout, audit-once (дедуп), норма не в readout, API+RBAC.

Проверка: локально `ruff` + сбор тестов (БД-тесты скипаются без Postgres, #12) → CI ветки (Postgres) зелёный → merge.

Последний коммит: d6c64d2
- [~] 1. periods.py — _blocked_reason (единый источник) + generate_due_periods использует его
- [ ] 2. periods.py — _record_skip (дедуп-аудит по границе+причине) + stuck_billing_accounts (readout)
- [ ] 3. routes_billing.py — GET /v1/billing/stuck-accounts (operator)
- [ ] 4. tests — readout / audit-once / норма-не-stuck / API+RBAC
- [ ] 5. ruff + сбор тестов локально → push ветку → CI зелёный
- [ ] 6. merge --no-ff в main + push; wiki (log/roadmap/QUEUE)
