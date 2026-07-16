---
type: progress
title: MFC-F3-1 — CRM-схема (clients + exchange_accounts + активация FK instances)
tags: [f3, crm, schema, migration-0005, adr-0013]
updated: 2026-07-14
sources: [wiki/concepts/domain-model.md, wiki/decisions/0013-instances-deferred-fk.md]
---
# progress: MFC-F3-1 — CRM-схема (первая фича Ф3)

Цель: материализовать родителей `clients` и `exchange_accounts` (domain-model) и АКТИВИРОВАТЬ
отложенные FK у instances (client_id, account_id — ADR-0013 «триггер включения»). Деньги НЕ трогаем
(комиссия/биллинг — отдельная фича после финализации ADR-0011). Оператор: «начинай параллельно».
bot_type_id/profile_id — FK остаются отложенными (родители в Ф5).

Последний коммит: 01cff77

## Развилка миграции (решаю сам, ADR-0013 предусмотрел «бэкофилл при необходимости»)
Демо-инстанс в облаке имеет случайные client_id/account_id без родителей (bootstrap-обход #15).
Добавить FK на живой БД с сиротами = миграция упадёт. Решение: миграция 0005 ДО добавления FK делает
**бэкофилл-плейсхолдеры** — по distinct instances.client_id вставляет clients-строки (name='(backfill)',
is_active=false), по distinct instances.account_id — exchange_accounts-строки. Затем bootstrap сеет
нормальный демо-client+account идемпотентно. Так FK включаются без потери существующих строк.

## Файлы, которые трогаем
- `core/alembic/versions/0005_crm.py` (новая миграция)
- `core/app/models.py` (модели Client, ExchangeAccount)
- `core/app/bootstrap.py` (seed демо-client + exchange_account под демо-инстанс)
- `core/tests/test_crm_schema.py` (новый), при нужде правка `core/tests/conftest.py` (TRUNCATE список)

## Под-шаги
- [x] 1. Модели `Client`, `ExchangeAccount` в models.py (+ комментарии «зачем», закон 7)
- [x] 2. Миграция 0005: clients + exchange_accounts (comments, CHECK fee/enum) → бэкофилл-плейсхолдеры →
      FK instances.client_id→clients, instances.account_id→exchange_accounts (ondelete=RESTRICT)
- [x] 3. bootstrap: seed демо-client + exchange_account (идемпотентно) под демо-инстанс
- [x] 4. Тесты (test_crm_schema + 5 существующих через хелпер ensure_parents): FK бьёт, CHECK fee/enum,
      бэкофилл-миграция (downgrade→сирота→upgrade), bootstrap-родители, create_instance 404/400
- [x] 5. CHECK: ruff clean, alembic head=0005, **CI зелёный (core-джоба, Postgres в облаке)** — БД-тесты
      локально не гонял (докер не поднимаю, #12). Само-ревью: 2 фикса (порядок _clean; принадлежность счёта)
- [x] 6. Ветка task/f3-crm-schema (d550edb) → merge в main (532399c); roadmap/log/QUEUE ✓

## Само-ревью (адверсариальное) — найдено и закрыто
- `_clean()` в тесте удалял instances до детей (commands/…) → FK-нарушение. Порядок исправлен.
- `create_instance` не проверял, что счёт принадлежит клиенту → инстанс связал бы клиента A со счётом B,
  биллинг Ф3 списал бы equity не тому. Добавлена проверка → 400 + тест.

## Границы
Деньги/комиссия НЕ здесь (ждём финализации ADR-0011 Куратором). key_ciphertext — nullable-колонка,
реальное конверт-шифрование = Ф2-хвост/go-live. Реальные ключи биржи НЕ трогаем. contracts (договор) —
следующая фича вместе с биллингом (fee-термины зависят от модели).

## Отложено в этой фиче (не забыть)
- contracts-таблица (договор) — с биллинг-фичей.
- CRM API (CRUD клиент/счёт оператором + RBAC + аудит) — следующая фича MFC-F3-2.
- Wiki-lint: domain-model:52 «billing_periods v1 таблица есть» неверно — починить при касании домен-модели.
