"""DynamicUniverse (S8, ADR-0019) — логика стека + интеграция findings_for_universe.

Логику стека (пол на пустоту / наполнение / анти-thrash / гистерезис / кап / нормализация) проверяем
на фейковом источнике — это НАШ код, не контракт вендора. findings_for_universe читает НАСТОЯЩУЮ
scout.db через build_scout (контракт #52): здесь — против реального storage.db.
"""
import json
import types

from app.dynamic_universe import DynamicUniverse


class _FakeScout:
    def __init__(self):
        self.data = (0, [])

    def findings_for_universe(self):
        return self.data


def _mk(tmp_path, **kw):
    d = dict(dynamic_coins_path=str(tmp_path / "coins.json"), dynamic_stack_max=3,
             dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0)
    d.update(kw)
    fs = _FakeScout()
    return DynamicUniverse(types.SimpleNamespace(**d), fs), fs


def test_no_scan_is_floor_no_file(tmp_path):
    dv, fs = _mk(tmp_path)
    dv.tick(1.0)
    assert dv.view()["count"] == 0
    assert not (tmp_path / "coins.json").exists()      # пол на пустоту: нет скана → нет файла


def test_fills_and_writes_valid_coins(tmp_path):
    dv, fs = _mk(tmp_path)
    fs.data = (1000, [{"symbol": "btcusdt", "tf": "4h", "state": "ready", "score": 90},
                      {"symbol": "ETHUSDT", "tf": "4h", "state": "tracking", "score": 70}])
    dv.tick(2.0)
    v = dv.view()
    assert v["cap"] == 3 and v["count"] == 2
    assert v["items"][0]["symbol"] == "BTCUSDT"        # нормализация регистра + сорт по скору
    coins = json.load(open(tmp_path / "coins.json"))
    assert set(coins) == {"BTCUSDT", "ETHUSDT"}
    assert coins["BTCUSDT"] == {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                "leverage": 5, "weight": 1.0}


def test_same_scan_no_rewrite(tmp_path):
    dv, fs = _mk(tmp_path)
    fs.data = (1000, [{"symbol": "BTCUSDT", "tf": "4h", "state": "ready", "score": 90}])
    dv.tick(2.0)
    before = (tmp_path / "coins.json").read_text()
    dv.tick(3.0)                                        # тот же scan_ms → no-op (анти-thrash)
    assert (tmp_path / "coins.json").read_text() == before


def test_cap_enforced(tmp_path):
    dv, fs = _mk(tmp_path)
    fs.data = (1000, [{"symbol": f"C{i}USDT", "tf": "4h", "state": "ready", "score": i}
                      for i in range(5)])
    dv.tick(2.0)
    assert dv.view()["count"] == 3                      # кап N=3 держит потолок из 5 кандидатов


def test_hysteresis_exit_after_exit_scans(tmp_path):
    dv, fs = _mk(tmp_path)                              # exit_scans=2
    fs.data = (1000, [{"symbol": "BTCUSDT", "tf": "4h", "state": "ready", "score": 90}])
    dv.tick(2.0)
    fs.data = (2000, [])
    dv.tick(3.0)                                        # missed=1 < exit → держим слот
    assert "BTCUSDT" in {i["symbol"] for i in dv.view()["items"]}
    fs.data = (3000, [])
    dv.tick(4.0)                                        # missed=2 ≥ exit → слот свободен
    assert dv.view()["count"] == 0


def test_empty_market_keeps_last_file(tmp_path):
    dv, fs = _mk(tmp_path)
    fs.data = (1000, [{"symbol": "BTCUSDT", "tf": "4h", "state": "ready", "score": 90}])
    dv.tick(2.0)
    fs.data = (2000, [])
    dv.tick(3.0)
    fs.data = (3000, [])
    dv.tick(4.0)                                        # стек пуст, но пустым файл НЕ перезаписан
    assert dv.view()["count"] == 0
    assert json.load(open(tmp_path / "coins.json"))    # держит последний валидный набор


def test_inactive_stage_ignored(tmp_path):
    dv, fs = _mk(tmp_path)
    fs.data = (1000, [{"symbol": "BTCUSDT", "tf": "4h", "state": "committed", "score": 90}])
    dv.tick(2.0)
    assert dv.view()["count"] == 0   # committed — производная UI, не стадия печки


def test_findings_for_universe_empty_real_scout_db(tmp_path):
    """findings_for_universe против НАСТОЯЩЕЙ storage.db (не мок): пустая печка → (0, []).
    Поля находок (symbol/tf/state/score) едут через build_scout — контракт #52."""
    from storage.db import DB

    from app.scout_reader import ScoutReader

    path = str(tmp_path / "scout.db")
    DB(db_path=path, owner=True)                        # создаёт схему scout; находок нет
    reader = ScoutReader(scout_db_path=path, worker_reader=object(),
                         detector_version="test", producer="test")
    scan_ms, findings = reader.findings_for_universe()
    assert scan_ms == 0 and findings == []              # скаут не сканил → нечего давать боту
    reader.close()


def test_engine_state_stack_only_when_provided():
    """mapper.engine_state: stack ТОЛЬКО при динамике; без него ключа нет (Персиваль чист)."""
    from app import mapper
    assert "stack" not in mapper.engine_state({})
    st = mapper.engine_state({}, stack={"cap": 10, "count": 1, "items": [{"symbol": "BTCUSDT"}]})
    assert st["stack"]["count"] == 1 and st["stack"]["cap"] == 10
