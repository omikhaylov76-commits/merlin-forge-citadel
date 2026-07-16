"""Sync-гвоздь версии Контракта + валидность scout-канала (ADR-0016, #50).

1) CONTRACT_VERSION картриджа == версия в `$id` ВСЕХ схем (включая пятый, scout-канал) — бамп v0→v1
   роняет тест, если забыли константу/схему.
2) Scout-схема валидна как JSON Schema 2020-12 и её examples проходят валидацию (schema-first гвоздь).
Pydantic-зеркало scout-снимка живёт на стороне ядра-приёмника (#52), где есть pydantic; картридж снимок
ПРОИЗВОДИТ и валидирует jsonschema (namely: минимум зависимостей, config.py) — здесь schema↔константа.
"""

import json
import re
from pathlib import Path

import jsonschema
from jsonschema import Draft202012Validator

from app.config import CONTRACT_VERSION

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_FMT = jsonschema.FormatChecker()
_ALL_SCHEMAS = (
    "telemetry-heartbeat.schema.json",
    "telemetry-equity.schema.json",
    "telemetry-trades.schema.json",
    "telemetry-events.schema.json",
    "command.schema.json",
    "telemetry-scout.schema.json",
)


def _schema(name: str) -> dict:
    return json.loads((_CONTRACTS / name).read_text(encoding="utf-8"))


def _schema_version(sid: str) -> str:
    m = re.search(r"/contracts/(v\d+)/", sid)
    assert m, f"не распарсить версию из $id {sid}"
    return m.group(1)


def test_contract_version_matches_all_schema_ids():
    for name in _ALL_SCHEMAS:
        assert _schema_version(_schema(name)["$id"]) == CONTRACT_VERSION, (
            f"{name}: версия $id != CONTRACT_VERSION ({CONTRACT_VERSION})"
        )


def test_scout_schema_valid_and_examples_pass():
    s = _schema("telemetry-scout.schema.json")
    Draft202012Validator.check_schema(s)  # сама схема — валидный JSON Schema
    validator = Draft202012Validator(s, format_checker=_FMT)
    examples = s.get("examples", [])
    assert examples, "scout-схема: нет examples для проверки"
    for i, ex in enumerate(examples):
        errors = sorted(validator.iter_errors(ex), key=str)
        assert not errors, f"scout example[{i}] невалиден: {[e.message for e in errors]}"


def test_scout_schema_field_structure():
    """Структурный гвоздь (замена Pydantic-зеркала на стороне картриджа, ADR-0016): множество полей
    scout-снимка, required и enum'ы прибиты руками — дрейф СТРУКТУРЫ (добавили/убрали/переименовали
    поле, поменяли enum/кап) роняет тест. Полное Pydantic-зеркало снимка — в ядре-приёмнике (#52).
    """
    item = _schema("telemetry-scout.schema.json")["items"]
    props = item["properties"]
    assert set(props) == {
        "symbol", "tf", "state", "score", "bars_since_anchor", "levels", "klines_tf", "klines",
        "orders", "position", "scan_ts", "orders_ts", "data_upto", "detector_version",
        "config_fingerprint", "config_mismatch", "producer",
    }
    assert set(item["required"]) == {
        "symbol", "tf", "state", "score", "scan_ts", "orders_ts", "data_upto",
        "detector_version", "config_fingerprint", "config_mismatch", "producer",
    }
    assert props["tf"]["enum"] == ["4h", "1h"]
    assert props["state"]["enum"] == ["forming", "tracking", "ready"]
    assert props["klines_tf"]["enum"] == ["15m", "5m"]
    assert set(props["levels"]["items"]["properties"]["role"]["enum"]) == {
        "A", "B", "entry_0382", "entry_05", "entry_0618", "stop",
    }
    assert props["klines"]["maxItems"] == 500  # кап свечей директивы #50
    assert set(props["orders"]["items"]["properties"]) == {
        "order_id", "side", "type", "px", "qty", "status",
    }
    assert set(props["position"]["properties"]) == {"side", "avg_px", "size", "live_pnl"}
