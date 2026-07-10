---
type: concept
title: Домен-модель ядра
tags: [architecture, domain, schema]
updated: 2026-07-10
sources: [decisions/0001…0011, concepts/seams.md]
---
# Домен-модель (единый источник таблиц; миграция 0001 строится ОТСЮДА)

Правило: это единственное место, где перечислены таблицы; architecture/seams ССЫЛАЮТСЯ, не дублируют.
Заглушки-трубы физически присутствуют (иначе FK некуда, «молчаливая полудорога» запрещена), но
в v1 не наполняются. Все id — UUID (не последовательные: закрывает перебор cmd_id, SEC7).

## Люди и клиенты
- **users**(id, role[operator|client], totp_secret?, created_at) — Оператор с TOTP; клиенты v1 — пароль.
- **clients**(id, name, contacts, contract_ref, fee_pct_default, user_id?) — тариф по умолчанию тут (MON8).
- **api_tokens**(id, principal[instance|ensemble|orchestrator|user], subject_id, token_hash, scope,
  created_at, revoked_at) — ADR-0008: отзыв = revoked_at; hash, не сам токен.

## Движки и профили
- **bot_types**(id, name, image_digest, version, contract_version) — образ по allowlist-digest (ADR-0010v2).
- **profiles**(id, bot_type_id, config_json, status[draft|passported])
- **passports**(profile_id, oos_metrics_json, engine_commit, data_range, created_at) — без OOS не создаётся (constraint).
- **exchange_accounts**(id, client_id, exchange[bybit|okx|bitget], label, key_ciphertext, perms_checked_at)
- **exchange_capabilities**(exchange, features_json) — труба бирж (v1: одна строка bybit).

## Инстансы и управление
- **instances**(id, client_id, account_id, bot_type_id, profile_id, status, health[ok|stale|dead],
  last_heartbeat_at, infra_ref, ensemble_id?, deployed_at) — status=намерение, health=свежесть (flows).
  Constraint: ≤1 инстанс на account_id в живых статусах (OPS3/MON2).
- **ensembles**(id, name, created_at) — труба дирижёра (ADR-0006; v1 не наполняется).
- **commands**(id, instance_id, kind[pause|resume|stop_close], status[queued|delivered|acked|failed],
  result_json, created_at, acked_at) — очередь команд боту (ADR-0002/0005). cmd_id = этот id.
- **challenges**(id, subject, action, expires_at, consumed_at) — серверное 2-е подтверждение stop_close (S2).
- **jobs**(id, instance_id, kind[deploy|teardown|backtest⌫резерв], payload_json, status[queued|leased|done|failed],
  lease_expires_at, attempts, created_at) — аренда+идемпотентность (ADR-0009). kind=teardown (не «stop»).

## Телеметрия (недоверенный ввод — экранировать, SEC5)
- **equity_points**(instance_id, ts, equity, working?, cushion?) · **trades**(instance_id, ts, exec_id,
  symbol, side, qty, pnl, …) · **events**(instance_id, ts, kind, detail) — heartbeats НЕ таблица,
  а instances.last_heartbeat_at (SCL9). Индекс (instance_id, ts DESC); ретеншн сырья ~90д→агрегаты (SCL5).
  Дедуп: trades по (instance_id, exec_id биржи); equity/events по (instance_id, ts, kind) (OPS8/COH4).

## Деньги, приём ключей, аудит, наблюдаемость
- **billing_periods**(id, account_id, client_id, start, end, start_equity, end_equity, hwm, fee_pct,
  fee_amount, status, adjustments_json) — МОДЕЛЬ HWM целиком в ADR-0011 (Ф3): cashflows, перенос
  hwm, валюта, сверка. v1 таблица есть, математика — по 0011.
- **cashflows**(id, account_id, kind[deposit|withdrawal], amount, ts, actor) — Ф3, ADR-0011 (MON1).
- **key_intake_links**(id, account_id?, token_hash, expires_at, consumed_at) — одноразовая форма S8.
- **outbox_events**(id, kind, severity, payload_json, created_at, dispatched_at, attempts) — durable
  алерты, диспетчер с приоритетом+dead-man (SCL3). **research_artifacts**(id, kind, title, body/link, tags).
- **audit_log**(id, actor, action, entity, before/after, ts) — append-only, закон №4.
