"""Соответствие Контракту: payload'ы адаптера валидны против contracts/*.schema.json (schema-first).

Мок-ядро в тестах не валидирует тело — эти тесты закрывают пробел: реальное ядро (MFC-005) отвергло
бы невалидный payload. FormatChecker проверяет format=date-time у ts. Схемы — единый источник.
"""

import json
from pathlib import Path

import jsonschema

from app import mapper

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_FMT = jsonschema.FormatChecker()


def _schema(name: str) -> dict:
    return json.loads((_CONTRACTS / name).read_text())


def _monitor() -> dict:
    return {
        "status": {"stale": False},
        "capital": {"equity": 1200.5, "working": 1000.0, "cushion": 200.5,
                    "killswitch_active": False},
        "trades": [{"id": 1, "created_ms": 1_700_000_000_000, "symbol": "BTCUSDT",
                    "side": "Sell", "qty": 0.01, "closed_pnl": 12.5, "dedup_key": "dk-1"}],
        "events": [{"id": 1, "ts": "2026-07-11T12:00:00+00:00", "symbol": "BTCUSDT",
                    "event": "entry_filled", "detail": '{"leg": 1}'}],
    }


def test_heartbeat_payload_valid():
    for status in ("running", "paused", "stopping", "error"):
        payload = {"status": status, "uptime_s": 1.0, "contract_version": "v1"}
        jsonschema.validate(payload, _schema("telemetry-heartbeat.schema.json"),
                            format_checker=_FMT)


def test_equity_payload_valid():
    point = mapper.equity_point(_monitor(), ts_iso="2026-07-11T12:00:00+00:00")
    jsonschema.validate(point, _schema("telemetry-equity.schema.json"), format_checker=_FMT)


def test_trades_payload_valid():
    batch, _ = mapper.trades_batch(_monitor(), after_id=0)
    jsonschema.validate(batch, _schema("telemetry-trades.schema.json"), format_checker=_FMT)


def test_events_payload_valid():
    batch, _ = mapper.events_batch(_monitor(), after_id=0)
    jsonschema.validate(batch, _schema("telemetry-events.schema.json"), format_checker=_FMT)


def test_all_heartbeat_status_mappings_in_enum():
    """Любой маппинг heartbeat_status обязан попадать в enum схемы (иначе ядро отвергнет)."""
    allowed = set(_schema("telemetry-heartbeat.schema.json")["properties"]["status"]["enum"])
    for killed in (True, False):
        for paused in (True, False):
            for stale in (True, False):
                m = {"capital": {"killswitch_active": killed}, "status": {"stale": stale}}
                assert mapper.heartbeat_status(m, paused=paused) in allowed
