"""Гвоздь на конфиг: heartbeat заклампен потолком Контракта (не реже раза в 60с)."""

import pytest

from app.config import from_env


def test_required_env_missing_raises(monkeypatch):
    monkeypatch.delenv("MF_INSTANCE_ID", raising=False)
    with pytest.raises(KeyError):
        from_env()  # без MF_INSTANCE_ID картридж не стартует


def test_heartbeat_interval_clamped_to_60(monkeypatch):
    monkeypatch.setenv("MF_INSTANCE_ID", "i")
    monkeypatch.setenv("MF_INSTANCE_TOKEN", "t")
    monkeypatch.setenv("MF_HEARTBEAT_S", "120")  # > потолка Контракта 60с
    assert from_env().heartbeat_interval_s == 60.0
