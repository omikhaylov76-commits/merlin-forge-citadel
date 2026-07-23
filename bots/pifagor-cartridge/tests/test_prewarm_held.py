"""Порция №2 «прогрев held» (S8) — тесты против НАСТОЯЩЕГО vendored config.strategy, НЕ моков.

Урок S7: вендор-интеграции на живом коде. Прогрев пишет coins.json из held ДО старта движка
(дефолт-бары); реальный `_load_coins_config` эту вселенную читает и принимает (REPLACE + validate).
Пол-на-пустоту: held пуст → не пишем. При DYNAMIC_ENABLED=0 (флот/paper) boot-шаг — no-op."""
import json

import config._env as cenv
import config.strategy as strat

from app.dynamic_universe import _write_coins_atomic, coin_block, prewarm_coins_from_held


def test_prewarm_writes_held_default_bars(tmp_path):
    path = str(tmp_path / "coins.json")
    n = prewarm_coins_from_held(path, frozenset({"BTCUSDT", "ETHUSDT"}))
    assert n == 2
    data = json.loads((tmp_path / "coins.json").read_text(encoding="utf-8"))
    assert set(data) == {"BTCUSDT", "ETHUSDT"}
    assert data["BTCUSDT"]["mb1"] == coin_block()["mb1"]   # дефолт-бары
    assert data["BTCUSDT"]["mb2"] == coin_block()["mb2"]
    assert (tmp_path / "coins.json.gen").read_text() == "0"   # первый скан (≠0) перезапишет


def test_prewarm_empty_held_no_write(tmp_path):
    path = str(tmp_path / "coins.json")
    assert prewarm_coins_from_held(path, frozenset()) == 0
    assert not (tmp_path / "coins.json").exists()          # пол-на-пустоту: файла нет


def test_prewarm_normalizes_and_dedups(tmp_path):
    path = str(tmp_path / "coins.json")
    n = prewarm_coins_from_held(path, {" btcusdt ", "BTCUSDT", "", "   "})
    assert n == 1  # регистр+пробелы+пустышка+пробельная → одна монета
    assert set(json.loads((tmp_path / "coins.json").read_text())) == {"BTCUSDT"}


def test_prewarm_coins_loadable_by_real_vendor(tmp_path, monkeypatch):
    """Движок прочитает прогрев: coins.json грузит вендорный _load_coins_config (REPLACE), validate
    доволен (fail-loud молчит), ключ leverage на месте."""
    path = str(tmp_path / "coins.json")
    prewarm_coins_from_held(path, frozenset({"BTCUSDT", "SOLUSDT"}))
    cenv.ENV_ERRORS.clear()
    monkeypatch.setenv("COINS_CONFIG_PATH", path)
    loaded = strat._load_coins_config()
    assert set(loaded) == {"BTCUSDT", "SOLUSDT"}           # вселенная замещена на held
    assert not cenv.ENV_ERRORS                             # без fail-loud → блок валиден
    assert loaded["BTCUSDT"]["leverage"] == coin_block()["leverage"]


def test_write_coins_atomic_file_gen_and_tmp_cleanup(tmp_path):
    path = str(tmp_path / "coins.json")
    _write_coins_atomic(path, {"BTCUSDT": coin_block()}, "12345")
    assert json.loads((tmp_path / "coins.json").read_text())["BTCUSDT"]["enabled"] is True
    assert (tmp_path / "coins.json.gen").read_text() == "12345"
    assert not list(tmp_path.glob(".coins.*"))             # temp прибран (атомарность)


def test_prewarm_main_dynamic_disabled_no_write(tmp_path, monkeypatch):
    """DYNAMIC_ENABLED≠1 (флот/paper): boot-шаг main → 0, БД не трогает."""
    import app.prewarm_held as ph
    monkeypatch.setenv("MF_INSTANCE_ID", "test")
    monkeypatch.setenv("MF_INSTANCE_TOKEN", "test")
    monkeypatch.delenv("DYNAMIC_ENABLED", raising=False)
    assert ph.main() == 0


def test_prewarm_main_best_effort_on_missing_env(monkeypatch):
    """Контракт best-effort: нет MF_* → from_env KeyError ловится, main → 0 (боот не падает)."""
    import app.prewarm_held as ph
    monkeypatch.delenv("MF_INSTANCE_ID", raising=False)
    monkeypatch.delenv("MF_INSTANCE_TOKEN", raising=False)
    assert ph.main() == 0
