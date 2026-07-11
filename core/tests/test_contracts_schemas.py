"""Schema-first гвоздь (MFC-005): схемы Контракта Бота v0 в contracts/ валидны как JSON Schema,
и их встроенные examples проходят валидацию. БД не нужна. Синхронизацию схема↔Pydantic-модели ядра
проверяет test_telemetry (шаг 4). Правка схемы без обновления моделей уронит эти тесты."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

_CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def _schema_files() -> list[Path]:
    return sorted(_CONTRACTS.glob("*.schema.json"))


def test_contracts_dir_has_schemas():
    names = {p.name for p in _schema_files()}
    # v0 Контракта: 4 канала телеметрии + ответ команд (bot-contract.md)
    assert {
        "telemetry-heartbeat.schema.json",
        "telemetry-equity.schema.json",
        "telemetry-trades.schema.json",
        "telemetry-events.schema.json",
        "command.schema.json",
    } <= names


@pytest.mark.parametrize("path", _schema_files(), ids=lambda p: p.name)
def test_schema_valid_and_examples_pass(path: Path):
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)  # сама схема — валидный JSON Schema
    validator = Draft202012Validator(schema)
    examples = schema.get("examples", [])
    assert examples, f"{path.name}: нет examples для проверки"
    for i, ex in enumerate(examples):
        errors = sorted(validator.iter_errors(ex), key=str)
        assert not errors, f"{path.name} example[{i}] невалиден: {[e.message for e in errors]}"
