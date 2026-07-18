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

⚠️ Компромисс окна (ревью #1): build_monitor отдаёт лишь новейшие TRADES_WINDOW/EVENTS_WINDOW строк
(закрытое recent-N). Если НАД курсором накопилось больше окна (многочасовой даунтайм ядра при
активной торговле ИЛИ первый коннект к БД с бэклогом), старые строки выскользнут из окна и курсор
их перепрыгнет = ПРОПУСК. Следствие «телеметрия только через build_monitor» (ADR-0001, faithful);
цикл детектит прыжок курсора >окна и логирует WARNING (bot._warn_scroll_gap). Полный фикс (курсорный
direct-read из БД в обход окна — тоже faithful, это сырой журнал, не агрегат) — в QUEUE Куратору.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

_SIDE = {"buy": "buy", "sell": "sell", "long": "buy", "short": "sell"}

# Окна build_monitor (db.closed_trades_recent(200) / events_recent(50)) — для детекта пропуска.
TRADES_WINDOW = 200
EVENTS_WINDOW = 50


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


# ── scout-снимок (5-й канал, ADR-0016 #52) — из состояния скаута → контрактный снимок ──────────
# ЧИСТЫЕ функции: принимают уже прочитанные примитивы (scout_reader читает БД). klines/klines_tf
# ОПУСКАЕМ — у скаута нет 15m/5m в Фазе 1 (ADR-0016 д); несём геометрию levels (свечи — #53).

# Статические допущения детектора скаута (scan.py:79 ema/shorts=False; :28 reanchor=True; :72
# STOP_FIB из env). Движок торгует по runtime-effective ConfigStore — расхождение видно (в.3).
_SCOUT_ASSUMPTIONS = {
    "SHORTS_ENABLED": False, "EMA_FILTER_ENABLED": False, "REANCHOR_AFTER_SCALP": True,
}


_MISMATCH_KEYS = ("SHORTS_ENABLED", "EMA_FILTER_ENABLED", "REANCHOR_AFTER_SCALP", "STOP_FIB")


def scout_config_mismatch(worker_eff: dict, *, scout_stop_fib: float) -> dict:
    """Сравнение 4 крутилок: эффективный конфиг движка vs допущения скаута. flag=true → консоль
    ОБЯЗАНА показать плашку. Крутилку, которой НЕТ в worker_eff (конфиг не прочитан), пропускаем —
    не поднимаем flag вслепую (иначе пустой eff дал бы ложную плашку по всем)."""
    assumed = {**_SCOUT_ASSUMPTIONS, "STOP_FIB": scout_stop_fib}
    details: dict = {}
    for key, scout_val in assumed.items():
        if key not in worker_eff:
            continue
        if worker_eff[key] != scout_val:
            details[key] = {"scout": scout_val, "worker": worker_eff[key]}
    return {"flag": bool(details), "details": details}


def _config_fingerprint(worker_eff: dict) -> str:
    """Отпечаток ЭФФЕКТИВНОГО конфига движка по крутилкам сетапа — меняется при смене конфига движка
    (консоль видит дрейф во времени). Детерминированный."""
    canon = json.dumps({k: worker_eff.get(k) for k in _MISMATCH_KEYS}, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()[:16]


def scout_levels(finding: dict) -> list[dict]:
    """A/B/входы 0.382/0.5/0.618/стоп из сырого payload находки (signal.py). forming → [] (нет
    уровней). Ключи entries после JSON — строки ('0.382')."""
    if finding.get("status") == "forming":
        return []
    entries = finding.get("entries") or {}
    raw = [
        ("B", finding.get("B")), ("A", finding.get("A")),
        ("entry_0382", entries.get("0.382")), ("entry_05", entries.get("0.5")),
        ("entry_0618", entries.get("0.618")), ("stop", finding.get("stop")),
    ]
    out = []
    for role, val in raw:
        price = _num(val)
        if val is not None and price > 0:
            out.append({"role": role, "price": price})
    return out


def scout_orders(orders_raw: list | None) -> list[dict]:
    """Реальные выставленные ордера (orders_open legs {level,entry,tgt,qty,filled,order_id}) →
    контрактные orders. px←entry, status←filled. В dry-run ордеров нет → []."""
    out = []
    for o in orders_raw or []:
        oid = o.get("order_id")
        px = _num(o.get("entry"))
        qty = _num(o.get("qty"))
        if not oid or px <= 0 or qty <= 0:
            continue
        out.append({
            "order_id": str(oid)[:80], "side": str(o.get("side") or "buy")[:8],
            "type": str(o.get("type") or "limit")[:16], "px": px, "qty": qty,
            "status": "filled" if o.get("filled") else "pending",
        })
    return out


def scout_klines(candles: list | None) -> list[dict]:
    """Свечи скан-ТФ из кэша скаута {time,open,high,low,close,volume} → контракт {time,o,h,l,c,v}.
    Кап ≤500 (окно скана скаута ≤300); битые бары пропускаем."""
    out = []
    for c in (candles or [])[-500:]:
        t = c.get("time")
        if t is None:
            continue
        out.append({
            "time": int(t), "o": _num(c.get("open")), "h": _num(c.get("high")),
            "l": _num(c.get("low")), "c": _num(c.get("close")), "v": _num(c.get("volume")),
        })
    return out


def scout_position(pos: dict | None) -> dict | None:
    """Позиция по символу (account.positions {side,size,avgPrice,unrealisedPnl}) → контракт."""
    if not pos:
        return None
    return {
        "side": str(pos.get("side") or "")[:8],
        "avg_px": _num(pos.get("avgPrice", pos.get("avg_px"))),
        "size": _num(pos.get("size")),
        "live_pnl": _num(pos.get("live_pnl", pos.get("unrealisedPnl"))),
    }


def scout_snapshot(
    finding: dict, *, worker_eff: dict, scout_stop_fib: float, orders_raw: list | None,
    position: dict | None, detector_version: str, producer: str,
    scan_ts_iso: str, orders_ts_iso: str, data_upto_iso: str,
    candles: list | None = None, klines_tf: str | None = None,
) -> dict:
    """Одна находка скаута → контрактный снимок. Несёт ВСЕ required схемы (вкл. data_upto).
    Свечи скан-ТФ (klines_tf = tf сетапа) — из кэша; младший ТФ прорисовки — задел (ADR-0016 д)."""
    snap = {
        "symbol": str(finding.get("symbol") or "")[:40],
        "tf": finding.get("tf") or "4h",
        "state": finding.get("status") or "forming",
        "score": _num(finding.get("score")),
        "scan_ts": scan_ts_iso, "orders_ts": orders_ts_iso, "data_upto": data_upto_iso,
        "detector_version": str(detector_version)[:40],
        "config_fingerprint": _config_fingerprint(worker_eff),
        "config_mismatch": scout_config_mismatch(worker_eff, scout_stop_fib=scout_stop_fib),
        "producer": str(producer)[:40],
    }
    levels = scout_levels(finding)
    if levels:
        snap["levels"] = levels
    if finding.get("bars_since_anchor") is not None:
        snap["bars_since_anchor"] = int(finding["bars_since_anchor"])
    orders = scout_orders(orders_raw)
    if orders:
        snap["orders"] = orders
    pos = scout_position(position)
    if pos is not None:
        snap["position"] = pos
    klines = scout_klines(candles)
    if klines:
        snap["klines"] = klines
        snap["klines_tf"] = klines_tf or snap["tf"]  # = tf сетапа (свечи скан-ТФ)
    return snap


# ── карточка бота (S7): engine_state — компакт движкового состояния для факт-вью Оператора ──
def _recent_trades(monitor: dict, n: int = 10) -> list[dict]:
    out = []
    for r in (monitor.get("trades") or [])[:n]:            # closed_trades_recent — новые сверху
        out.append({
            "symbol": str(r.get("symbol") or "")[:40], "side": str(r.get("side") or "")[:8],
            "qty": _num(r.get("qty")), "pnl": _num(r.get("closed_pnl")),
            "ts": _iso_from_ms(r.get("created_ms")),
        })
    return out


def _recent_events(monitor: dict, n: int = 10) -> list[dict]:
    out = []
    for r in (monitor.get("events") or [])[:n]:
        out.append({
            "kind": str(r.get("event") or r.get("kind") or "")[:40],
            "ts": str(r.get("ts") or "")[:40], "detail": str(r.get("detail") or "")[:200],
        })
    return out


def held_symbols(monitor: dict) -> frozenset[str]:
    """Символы с ЖИВЫМ money-следом: открытая позиция (size≠0) ИЛИ висящий ордер (pending).

    Источник пина Вехи 2 (ADR-0019 «б», F-pin-scope Оператора): монета пришпилена, пока по ней есть
    позиция ИЛИ ордер; отпуск — ТОЛЬКО когда пусто И то, и другое. Читаем ОБА источника из того же
    build_monitor, что engine_state (единый факт-слой, 0 vendor). Регистр → upper (== ключи стека
    провайдера). Пустой/битый монитор → ∅ (пин безвреден; флот с held=∅, динамика выкл)."""
    held: set[str] = set()
    for p in monitor.get("positions") or []:
        if _num(p.get("size")):                             # плоские/нулевые — слот не занят
            sym = str(p.get("symbol") or "").strip().upper()
            if sym:
                held.add(sym)
    for row in monitor.get("pending") or []:                # висящий ордер по символу (любая нога)
        sym = str(row.get("symbol") or "").strip().upper()
        if sym:
            held.add(sym)
    return frozenset(held)


def engine_state(monitor: dict, stack: dict | None = None) -> dict:
    """Компакт движкового состояния для карточки бота: статус/капитал/позиции/ордера/хвосты сделок и
    событий. Из build_monitor — только ЧИТАЕМ (0 vendor). Секреты/ключи биржи НЕ кладём — лишь
    оператор-видимое (позиции/ордера/equity). Недоверенный JSON, экранируется на выводе.
    stack (S8, опц.): рабочая вселенная из печки {cap,count,items} — только при динамике; без неё
    ключа НЕТ (payload прежний, Персиваль/флот чисты)."""
    cap = monitor.get("capital") or {}
    st = monitor.get("status") or {}
    positions = []
    for p in monitor.get("positions") or []:
        if not _num(p.get("size")):
            continue                                        # плоские/нулевые не показываем
        pos = scout_position(p)
        if pos:
            pos["symbol"] = str(p.get("symbol") or "")[:40]
            positions.append(pos)
    orders = []
    for row in monitor.get("pending") or []:
        sym = str(row.get("symbol") or "")[:40]
        payload = row.get("payload") or {}
        legs = [{**leg, "side": payload.get("side")} for leg in payload.get("legs") or []]
        for o in scout_orders(legs):
            o["symbol"] = sym
            orders.append(o)
    ks = bool(cap.get("killswitch_active"))
    state = str(cap.get("state") or ("stopping" if ks else "running"))[:16]
    out = {
        "status": {
            "state": state,
            "kill_switch": ks,
            "alarm": bool(cap.get("alarm_active")),
            "stale": bool(st.get("stale")),
            "banner": str(st.get("banner") or "")[:200],
        },
        "capital": {
            "equity": _num(cap.get("equity")), "peak": _num(cap.get("peak_equity")),
            "dd_pct": _num(cap.get("dd_pct")), "unrealised_pnl": _num(cap.get("unrealised_pnl")),
            "realised_pnl": _num(cap.get("realised_pnl")),
            "open_count": int(cap.get("open_count") or 0),
        },
        "positions": positions,
        "orders": orders,
        "trades": _recent_trades(monitor),
        "events": _recent_events(monitor),
    }
    if stack is not None:
        out["stack"] = stack          # S8: рабочая вселенная (символ+стадия) для карточки Борса
    return out
