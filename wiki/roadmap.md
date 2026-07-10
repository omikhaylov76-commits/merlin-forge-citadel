---
type: roadmap
title: Дорожная карта Merlin Forge Citadel
tags: [roadmap, phases]
updated: 2026-07-10
sources: [handoffs/HANDOFF_2026-07-10_session_1.md]
---
# Roadmap: вехи → фичи

Оценка всего пути (Ф0→Ф5): 22–35 сессий. Статусы: todo / in-progress / done.

## Ф0 — Подготовка (in-progress, ~80%)
Цель: конституция, решения, скелет, база знаний — фундамент до первой строчки кода.
- [x] Концепция + 6 ADR (0001–0006) — done
- [x] Вики по паттерну Карпати (index/log/concepts/entities/…) — done
- [x] Скелет монорепо (модули + README-манифесты границ) — done
- [x] Перевод проекта под Maestro Kit (/build) — done
- [ ] CLOSURE-1: git init + приватный GitHub + push — in-progress · merged: no
- [ ] Мокап консоли на дизайн-токенах Оператора — todo · блокер: дизайн-папка в iCloud не скачана
- [ ] Юрисдикция/договор — за Оператором (async, до первого внешнего клиента), не блокер кода

## Ф1 — Forge: флот на paper-bot (todo)
Цель: конвейер платформы целиком, без денег — на бумажном боте.
- [ ] MFC-001 core-скелет: FastAPI + Alembic + миграция 0001 (users/roles/audit_log) + TOTP-заготовка + /healthz + pytest — todo
- [ ] Оркестратор + InfraDriver (Railway GraphQL; интерфейс абстрагирован, план Б — DockerDriver) — todo
- [ ] paper-bot: картридж по Контракту Бота v0, push-телеметрия + JSON-схемы (schema-first) — todo
- [ ] Обкатка Railway API на живом инстансе paper-bot (проверка допущения №3 handoff'а) — todo
- [ ] Консоль Оператора: минимальный флот-дашборд (после мокапа) — todo

## Ф2 — Пифагор-картридж (todo)
Цель: первый боевой движок за Контрактом, без правок pifagor-v81.
- [ ] Recon: storage/db.py и dashboard/viewmodel.py — проверить допущение «обёртка без правок репо» — todo
- [ ] Обёртка-образ: адаптер телеметрии + heartbeat ≤60с отдельным циклом — todo
- [ ] Конверт-шифрование ключей биржи end-to-end (ADR-0004) + тесты — todo

## Ф3 — CRM + биллинг HWM (todo)
Цель: клиенты, договорные параметры, комиссия % от прибыли по high-water mark.
- [ ] CRM-модель: клиент → договор → инстансы — todo
- [ ] Биллинг HWM + обязательные тесты (закон 8) — todo
- [ ] Алерты Оператору в Telegram (runbooks/alerts) — todo

## Ф4 — Клиентский портал (todo)
Цель: read-only портал + ровно две команды (ADR-0005).
- [ ] Портал: доходность/статус, без управления — todo
- [ ] PAUSE (мгновенно) + STOP_CLOSE (двойное подтверждение) через API ядра + аудит — todo

## Ф5 — Кузница-UI (todo)
Цель: библиотека профилей с паспортами (паспорт без OOS не существует).
- [ ] Библиотека профилей + паспорта (research/passport-spec) — todo
- [ ] UI Кузницы в консоли — todo

## Icebox (по одной строке, не в работу)
- Ансамбли: UI бота-дирижёра (труба заложена, ADR-0006; UI в v1 нет).
- Биржи OKX / BitGet — подключение после Bybit (трубы готовы, entities есть).
- Static IP Railway — пересмотр риска на mainnet-объёмах (ADR-0003).
- Идеи gbrain — для Исследований (summaries/gbrain).
- Railway Pro — не включать до Ф1–2 (решение D2).
