---
type: progress
title: НАБОР-1 — корзина отмеченных сетапов (витрина + хранение)
tags: [progress, basket, nabor, phase7]
updated: 2026-07-17
---
# НАБОР-1 — Набор Оператора (витрина + хранение)

Последний коммит: см. git log (feat #НАБОР-1). ADR: [[0017-basket-nabor-1]]. Ничего не торгует.

## Шаги
- [x] Ядро: модель `BasketItem` + миграция 0012 (`basket_items`, uniq symbol+tf, aддитивно).
- [x] Ядро: роутер `/v1/basket` — GET/POST(upsert)/DELETE; операторский; audit add/remove (закон №4).
- [x] Тесты: add/dedup/remove + RBAC клиент-403 + 404 + bad-source-422 (4/4 на реальном PG).
- [x] Консоль: api getBasket/addToBasket/removeBasketItem + типы.
- [x] Консоль: пункт «Набор» в Кузнице + экран-список (монета/ТФ/источник/скор/стадия/время + «убрать»).
- [x] Консоль: звёздочка-тумблер на детали сетапа Разведки (ScoutDetail).
- [x] Деплой ядра (0012, serviceInstanceDeploy SUCCESS) + консоли (railway up, бандл живой). Боевой роут /v1/basket проверен end-to-end на облаке (add/list/remove). UI-клик — за Оператором (логин под паролем).
- [x] Звёздочка на сетап-чипах Скринера (source=screener) — per (монета,ТФ), задеплоено.
- [ ] (отдельно, спека Куратора) НАБОР-2 — «запустить в работу» боту.
