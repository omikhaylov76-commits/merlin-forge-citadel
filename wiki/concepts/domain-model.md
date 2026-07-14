---
type: concept
title: Домен-модель ядра
tags: [architecture, domain, schema]
updated: 2026-07-11
sources: [decisions/0001…0011, concepts/seams.md]
---
# Домен-модель (единый источник таблиц; миграции 0001–0004 строятся ОТСЮДА)

Правило: это единственное место, где перечислены таблицы; architecture/seams ССЫЛАЮТСЯ, не дублируют.
Заглушки-трубы физически присутствуют (иначе FK некуда, «молчаливая полудорога» запрещена), но
в v1 не наполняются. Все id — UUID (не последовательные: закрывает перебор cmd_id, SEC7).

## Люди и клиенты
- **users**(id, role[operator|client], totp_secret?, created_at) — Оператор с TOTP; клиенты v1 — пароль.
- **clients**(id, name, contacts, contract_ref, fee_pct_default, user_id?, is_active) — тариф по умолчанию тут (MON8). Материализована в 0005 (Ф3).
- **api_tokens**(id, principal[instance|ensemble|orchestrator|user], subject_id, token_hash, scope,
  created_at, revoked_at) — ADR-0008: отзыв = revoked_at; hash, не сам токен.

## Движки и профили
- **bot_types**(id, name, image_digest, version, contract_version) — образ по allowlist-digest (ADR-0010v2).
- **profiles**(id, bot_type_id, config_json, status[draft|passported])
- **passports**(profile_id, oos_metrics_json, engine_commit, data_range, created_at) — без OOS не создаётся (constraint).
- **exchange_accounts**(id, client_id, exchange[bybit|okx|bitget], label, key_ciphertext, perms_checked_at, is_active) — материализована в 0005 (Ф3); FK instances.client_id/account_id включены.
- **exchange_capabilities**(exchange, features_json) — труба бирж (v1: одна строка bybit).

## Инстансы и управление
- **instances**(id, client_id, account_id, bot_type_id, profile_id, status, health[ok|stale|dead],
  last_heartbeat_at, infra_ref, ensemble_id?, deployed_at) — status=намерение, health=свежесть (flows).
  Constraint: ≤1 инстанс на account_id в живых статусах (OPS3/MON2).
  Материализована в миграции 0002 (MFC-003); FK на родителей отложены — ADR-0013. health ставит
  свёртка часового instance_health (ok→stale→dead по свежести heartbeat).
- **ensembles**(id, name, created_at) — труба дирижёра (ADR-0006; v1 не наполняется).
- **commands**(id, instance_id→FK, kind[pause|resume|stop_close], status[queued|delivered|acked|failed],
  result, created_at, delivered_at, acked_at) — очередь команд боту (ADR-0002/0005). cmd_id = id.
  Материализована 0004 (MFC-005); ix активных (queued|delivered) для long-poll; липкий stop_close (OPS1).
- **challenges**(id, subject, action, expires_at, consumed_at) — серверное 2-е подтверждение stop_close (S2).
- **jobs**(id, instance_id→FK, kind[deploy|teardown; backtest⌫резерв-CHECK], status[pending|leased|done|failed],
  attempts, lease_expires_at, lease_nonce, payload, result, created_at, updated_at) — аренда+идемпотентность+
  fencing (ADR-0009). Материализована в 0003 (MFC-004); партиал-индекс «≤1 активный deploy/инстанс» (OPS2).

## Телеметрия (недоверенный ввод — экранировать на выводе, SEC5) — материализована 0004 (MFC-005)
- **equity_points**(id, instance_id→FK, ts, received_at, equity[Numeric], currency, working?, cushion?) ·
  **trades**(id, instance_id→FK, ts, received_at, exec_id, symbol, side, qty, pnl?) · **events**(id,
  instance_id→FK, ts, received_at, kind, detail) — heartbeats НЕ таблица, а instances.last_heartbeat_at
  (SCL9). received_at авторитетно. Индекс (instance_id, ts DESC); ретеншн сырья ~90д→агрегаты (SCL5, Ф3).
  Дедуп: trades по (instance_id, exec_id биржи); equity по (instance, ts); events по (instance, ts, kind) (OPS8/COH4).

## Деньги, приём ключей, аудит, наблюдаемость
- **billing_periods**(id, account_id, client_id, start, end, start_equity, end_equity, hwm, fee_pct,
  fee_amount, status, adjustments_json) — МОДЕЛЬ HWM целиком в ADR-0011 (Ф3): cashflows, перенос
  hwm, валюта, сверка. Таблицы ещё НЕТ — материализуется в Ф3 ПОСЛЕ финализации формулы ADR-0011.
- **cashflows**(id, account_id, kind[deposit|withdrawal], amount, ts, actor) — Ф3, ADR-0011 (MON1); таблицы ещё нет.
- **key_intake_links**(id, account_id?, token_hash, expires_at, consumed_at) — одноразовая форма S8.
- **outbox_events**(id, kind, severity, payload_json, created_at, dispatched_at, attempts) — durable
  алерты, диспетчер с приоритетом+dead-man (SCL3). **research_artifacts**(id, kind, title, body/link, tags).
- **audit_log**(id, actor, action, entity, before/after, ts) — append-only, закон №4.
