"""Разъём внешней вселенной монет (ADR-0019, S8 «Динамо-близнец») — тесты против НАСТОЯЩЕГО
vendored config.strategy, НЕ моков (урок S7: вендор-интеграции проверяем на живом коде).

Гарантии: дефолт байт-в-байт (Персиваль/Галахад не задеты), REPLACE из файла, нормализация символов,
fail-loud в ENV_ERRORS (→ config.validate останавливает старт), холодный старт (файла нет) → дефолт,
ключ leverage всегда присутствует (main.py:234 берёт его прямым subscript)."""
import json

import config._env as cenv
import config.strategy as strat


def _load(monkeypatch, path):
    """Свежий вызов загрузчика с заданным (или снятым) COINS_CONFIG_PATH; ENV_ERRORS обнулён."""
    cenv.ENV_ERRORS.clear()
    if path is None:
        monkeypatch.delenv("COINS_CONFIG_PATH", raising=False)
    else:
        monkeypatch.setenv("COINS_CONFIG_PATH", str(path))
    return strat._load_coins_config()


def _write(tmp_path, obj):
    f = tmp_path / "coins.json"
    f.write_text(json.dumps(obj), encoding="utf-8")
    return f


def test_unset_returns_default_byte_identical(monkeypatch):
    """env не задан → ТОТ ЖЕ объект-эталон (Персиваль: 16 enabled), ни одной ошибки."""
    coins = _load(monkeypatch, None)
    assert coins is strat._DEFAULT_COINS_CONFIG
    assert sum(1 for c in coins.values() if c["enabled"]) == 16
    assert cenv.ENV_ERRORS == []


def test_valid_file_replaces_and_uppercases(tmp_path, monkeypatch):
    """Валидный файл → REPLACE всей вселенной, символы в верхнем регистре, без ошибок."""
    f = _write(tmp_path, {"kaitousdt": {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                        "leverage": 5, "weight": 1.0}})
    coins = _load(monkeypatch, f)
    assert list(coins) == ["KAITOUSDT"]
    assert coins is not strat._DEFAULT_COINS_CONFIG
    assert cenv.ENV_ERRORS == []


def test_broken_json_fail_loud_and_default(tmp_path, monkeypatch):
    """Битый JSON → возврат дефолта, НО проблема в ENV_ERRORS → config.validate() свалит старт."""
    f = tmp_path / "coins.json"
    f.write_text("{bad json", encoding="utf-8")
    coins = _load(monkeypatch, f)
    assert coins is strat._DEFAULT_COINS_CONFIG
    assert cenv.ENV_ERRORS  # не пусто → fail-loud


def test_junk_symbol_dropped_and_logged(tmp_path, monkeypatch):
    """Нетоварный символ отсеивается (+лог), нормальный проходит с апер-кейсом."""
    f = _write(tmp_path, {"FOO": {"enabled": True, "mb1": 2, "mb2": 3, "leverage": 5, "weight": 1},
                          "btcusdt": {"enabled": True, "mb1": 1.5, "mb2": 2.5,
                                      "leverage": 5, "weight": 1.0}})
    coins = _load(monkeypatch, f)
    assert list(coins) == ["BTCUSDT"]
    assert any("FOO" in e for e in cenv.ENV_ERRORS)


def test_path_set_missing_file_is_cold_start_default(tmp_path, monkeypatch):
    """Путь задан, но файла ещё нет (холодный старт до провайдера) → дефолт, это НЕ ошибка."""
    coins = _load(monkeypatch, tmp_path / "nope.json")
    assert coins is strat._DEFAULT_COINS_CONFIG
    assert cenv.ENV_ERRORS == []


def test_leverage_key_always_present_subscript_safe(tmp_path, monkeypatch):
    """Монета без leverage/weight: ключ leverage всё равно есть (=None) → main.py:234 subscript
    не KeyError, а config.validate поймает «не положителен» (fail-loud). weight по умолчанию 1.0."""
    f = _write(tmp_path, {"ETHUSDT": {"enabled": True, "mb1": 2.0, "mb2": 3.5}})
    coins = _load(monkeypatch, f)
    assert "leverage" in coins["ETHUSDT"] and coins["ETHUSDT"]["leverage"] is None
    assert coins["ETHUSDT"]["weight"] == 1.0


def test_non_object_root_is_fail_loud(tmp_path, monkeypatch):
    """Корень не объект (список) → дефолт + ошибка в ENV_ERRORS."""
    f = _write(tmp_path, ["BTCUSDT"])
    coins = _load(monkeypatch, f)
    assert coins is strat._DEFAULT_COINS_CONFIG
    assert cenv.ENV_ERRORS


def test_string_numbers_are_coerced(tmp_path, monkeypatch):
    """Числа строками ("5"/"2.0") приводятся к типу — НЕ уходят строкой в config.validate (там `<=`
    на строке = TypeError). leverage→int, mb1/mb2/weight→float."""
    f = _write(tmp_path, {"BTCUSDT": {"enabled": True, "mb1": "2.0", "mb2": "3.5",
                                      "leverage": "5", "weight": "1.0"}})
    coins = _load(monkeypatch, f)
    c = coins["BTCUSDT"]
    assert c["leverage"] == 5 and isinstance(c["leverage"], int)
    assert c["mb1"] == 2.0 and isinstance(c["mb1"], float)
    assert cenv.ENV_ERRORS == []


def test_non_numeric_value_fail_loud(tmp_path, monkeypatch):
    """Нечисло в поле-числе ("abc"/bool) → None + ENV_ERRORS (validate: «не положителен»);
    сырого TypeError в validate не будет."""
    f = _write(tmp_path, {"BTCUSDT": {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                      "leverage": "abc", "weight": 1.0}})
    coins = _load(monkeypatch, f)
    assert coins["BTCUSDT"]["leverage"] is None
    assert any("leverage" in e for e in cenv.ENV_ERRORS)
