"""Sync-гвоздь версии Контракта (ADR-0016, #50): CONTRACT_VERSION картриджа == версия в `$id` схем.

Не даёт разойтись объявленной ботом версии и версии контракта: бамп v0→v1 роняет тест, если забыли
константу (или наоборот — правку схем без константы). Pydantic-зеркало снимков — на стороне ядра (#52),
картридж намеренно без pydantic (config.py: минимум зависимостей) — здесь только schema↔константа.
"""

import json
import re
from pathlib import Path

from app.config import CONTRACT_VERSION

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_SCHEMAS = (
    "telemetry-heartbeat.schema.json",
    "telemetry-equity.schema.json",
    "telemetry-trades.schema.json",
    "telemetry-events.schema.json",
    "command.schema.json",
    "telemetry-scout.schema.json",  # paper-bot скаут не производит, но версию Контракта v1 прибивает целиком (симметрия с pifagor)
)


def _schema_version(name: str) -> str:
    sid = json.loads((_CONTRACTS / name).read_text(encoding="utf-8"))["$id"]
    m = re.search(r"/contracts/(v\d+)/", sid)
    assert m, f"{name}: не распарсить версию из $id {sid}"
    return m.group(1)


def test_contract_version_matches_schema_ids():
    for name in _SCHEMAS:
        assert _schema_version(name) == CONTRACT_VERSION, (
            f"{name}: версия $id != CONTRACT_VERSION ({CONTRACT_VERSION})"
        )
