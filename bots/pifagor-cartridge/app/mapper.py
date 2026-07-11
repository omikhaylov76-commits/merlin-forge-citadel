"""Маппер телеметрии: выход `build_monitor(...)` Пифагора → payload'ы Контракта Бота v0.

ЧИСТЫЙ модуль (без сети/БД) — легко тестируется и сверяется parity-тестом. Faithfulness: цифры берём
из того же `build_monitor`, что рисует родной дашборд Пифагора (Куратор #10, Вариант A).

Соответствие Пифагор → Контракт:
- heartbeat.status: killswitch_active→stopping · paused→paused · stale→error · иначе running.
- equity ← capital.equity (тайл) + working/cushion; currency=USDT (v0).
- trades ← closed_trades: ts←created_ms→ISO · exec_id←dedup_key (UNIQUE) · side←'Buy/Sell'→buy/sell
  · qty>0 · pnl←closed_pnl. Дедуп ядром по (instance, exec_id).
- events ← events: ts←ISO-строка воркера (_utcnow_iso) · kind←event · detail←parse(detail)+symbol.
  Дедуп ядром по (instance, ts, kind).

Курсоры по `id` (autoincrement PK, монотонен) отсекают отправленное — без повторной отсылки окна
каждый тик (ядро дедупит, но так дешевле). На рестарте курсор=0 → одно окно ре-отправится (дедуп).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

_SIDE = {"buy": "buy", "sell": "sell", "long": "buy", "short": "sell"}


def _num(v) -> float:
    """Число → float; None/мусор → 0.0 (телеметрия не должна падать на битом снимке)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _iso_from_ms(ms) -> str:
    """epoch-мс → RFC3339 UTC. Битое → 'сейчас' (|ts−now| ядро проверяет только у equity)."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC).isoformat()


def heartbeat_status(monitor: dict, *, paused: bool) -> str:
    """Самооценка бота. Приоритет: stop_close(латч) > pause > stale > running (stop_close сильнее
    паузы); stale = нет свежего heartbeat воркера → error."""
    cap = monitor.get("capital") or {}
    status = monitor.get("status") or {}
    if cap.get("killswitch_active"):
        return "stopping"
    if paused:
        return "paused"
    if status.get("stale"):
        return "error"
    return "running"


def equity_point(monitor: dict, *, ts_iso: str) -> dict:
    """Точка кривой доходности. equity = capital.equity (заголовочный тайл дашборда). USDT (v0)."""
    cap = monitor.get("capital") or {}
    return {
        "ts": ts_iso,
        "equity": _num(cap.get("equity")),
        "currency": "USDT",
        "working": _num(cap.get("working")),
        "cushion": _num(cap.get("cushion")),
    }


def _exec_id(row: dict) -> str:
    """Идемпотентный ключ сделки: dedup_key (UNIQUE у Пифагора). Фолбэк — order_id / id."""
    for k in ("dedup_key", "order_id"):
        v = row.get(k)
        if v:
            return str(v)
    return f"ct-{row.get('id')}"


def trades_batch(monitor: dict, *, after_id: int) -> tuple[list[dict], int]:
    """closed_trades (новые сверху) → батч Контракта (старые первыми) + новый курсор id. Отсекаем
    id<=after_id; невалидные (side∉buy/sell, qty<=0) пропускаем."""
    out: list[dict] = []
    cursor = after_id
    for row in monitor.get("trades") or []:
        rid = int(row.get("id") or 0)
        if rid <= after_id:
            continue
        cursor = max(cursor, rid)
        side = _SIDE.get(str(row.get("side") or "").strip().lower())
        qty = _num(row.get("qty"))
        if side is None or qty <= 0:
            continue                                        # схема Контракта: side enum + qty>0
        item = {
            "ts": _iso_from_ms(row.get("created_ms")),
            "exec_id": _exec_id(row),
            "symbol": str(row.get("symbol") or "")[:40],
            "side": side,
            "qty": qty,
        }
        if row.get("closed_pnl") is not None:
            item["pnl"] = _num(row.get("closed_pnl"))
        out.append(item)
    out.reverse()                                           # старые первыми (порядок ленты)
    return out, cursor


def _detail_obj(row: dict) -> dict:
    """events.detail (TEXT|JSON) → object Контракта. symbol приклеиваем, если есть."""
    detail: dict = {}
    raw = row.get("detail")
    if raw:
        try:
            parsed = json.loads(raw)
            detail = parsed if isinstance(parsed, dict) else {"text": str(raw)}
        except (TypeError, ValueError):
            detail = {"text": str(raw)}
    sym = row.get("symbol")
    if sym and sym != "ALL":
        detail.setdefault("symbol", sym)
    return detail


def events_batch(monitor: dict, *, after_id: int) -> tuple[list[dict], int]:
    """events (новые сверху) → батч Контракта (хронологически) + курсор id. ts воркера уже ISO."""
    out: list[dict] = []
    cursor = after_id
    for row in monitor.get("events") or []:
        rid = int(row.get("id") or 0)
        if rid <= after_id:
            continue
        cursor = max(cursor, rid)
        kind = str(row.get("event") or "")[:40]
        if not kind:
            continue
        ts = row.get("ts")
        out.append({
            "ts": str(ts) if ts else datetime.now(UTC).isoformat(),
            "kind": kind,
            "detail": _detail_obj(row),
        })
    out.reverse()
    return out, cursor
