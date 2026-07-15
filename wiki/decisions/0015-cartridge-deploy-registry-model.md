---
type: decision
title: ADR-0015 — Модель деплоя картриджей (публичный реестр на демо → приватный+registry-cred на go-live)
tags: [adr, deploy, railway, ghcr, registry, security, cartridge]
updated: 2026-07-15
sources: [_curator/DIRECTIVES.md#47, wiki/decisions/0003-railway-first.md]
---
# ADR-0015 — Модель деплоя картриджей: реестр образов и приватность

## Контекст
Оркестратор деплоит картридж бота на Railway из ghcr-образа (`RailwayDriver.deploy` →
`serviceCreate(source.image)` + `serviceInstanceDeploy`). Railway **приватные образы тянет только на
тарифе Pro** (живой API 2026-07-15: «Private registry credentials can only be set for Pro users»).
D2 (ADR-0003) запрещает включать Railway Pro на демо-этапе. Возник конфликт с ранним требованием
«картридж приватный + registry-cred» (#44–#46): на hobby оно физически невозможно. В Ф2 (#15/#17)
деплой картриджа работал именно потому, что образы были **публичными**.

## Решение (Куратор #47, по явному выбору Оператора)
- **Сейчас (демо/эксперимент, hobby): образ ПУБЛИЧНЫЙ в окне деплоя (вариант A).** Осознанно и
  ВРЕМЕННО. Обоснование: образ уже был публичным ~неделю (Ф2), деньги бумажные (Bybit-demo),
  маргинальная утечка кода движка низкая; Pro ради одного демо-этапа не берём.
- **go-live (реальные деньги / много клиентов): образ ПРИВАТНЫЙ + registry-cred (вариант B).**
  PAT `read:packages` на тарифе/драйвере с приватным pull — **Railway Pro ИЛИ Docker-драйвер**
  (ADR-0003 абстрагирует драйвер). Код движка в проде публично не держим. Pro Оператор оплатит на
  этом рубеже.
- **Вариант C (`railway up` из локальных исходников) — ОТКЛОНЁН** в пользу faithful-потока
  orchestrator→RailwayDriver→ghcr (платформенный деплой клиентских инстансов идёт через оркестратор,
  а не ad-hoc CLI-загрузку). Зафиксирован как rejected.

## Механизм (реализован, go-live-ready)
`RailwayDriver` умеет обе модели (ветка task/railway-private-pull влита, #47):
- `serviceInstanceDeploy(serviceId, environmentId)` после create/adopt — **нужен всегда** (serviceCreate
  сам контейнер не запускает); environmentId резолвится (production).
- `registryCredentials{username, password}` в serviceCreate при заданном `GHCR_PULL_TOKEN` — путь
  варианта B. На hobby **inert** (Pro-only; при пустом токене не шлётся → публичный pull). Креды — в env
  оркестратора, не в git/лог (закон №2).

## Последствия
- 🔴 На hobby приватный образ Railway **НЕ перетянет** при redeploy/restart/crash: запущенные боты живут
  до первого re-pull, затем падают на pull. Деплой/передеплой требует **окна публичности**: Оператор
  кратко возвращает пакет public → Инженер тянет → Оператор снова закрывает. Отражено в runbook деплоя.
- go-live-хвост: PAT сузить до `read:packages`-only (сейчас repo+write — Оператор идёт с ним для демо).

## Триггер пересмотра
Покупка Railway Pro ИЛИ переход на Docker-драйвер ИЛИ go-live (реальные ключи/деньги) → переключение на
вариант B (приватный образ по умолчанию, окно публичности больше не нужно).
