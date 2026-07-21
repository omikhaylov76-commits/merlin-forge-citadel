"""F-scout-snap (S8): verified-сетка и синтез снимков для held-монет.

Против НАСТОЯЩЕЙ scout.db (storage.DB, урок vendor-integration-tests-not-mocks): синтез снимка
для held-без-находки, подмена уровней реальной сеткой (plumbing через monkeypatch _verified_grid —
сама геометрия warm.classify доказана живыми прогонами), graceful-паденье реплея на короткой/плоской
серии (реальный vendor-вызов до конца).
"""
import json

from storage.db import DB

from app.scout_reader import ScoutReader

NOW = 1_700_000_000_000
FOUR_H = 4 * 3600 * 1000


class _WorkerDB:
    """Мини-двойник интерфейса worker.db, который читает ScoutReader (orders/positions)."""

    def __init__(self, orders_by=None, positions=None):
        self._orders = orders_by or {}
        self._positions = positions or []

    def orders_open_all(self):
        return [{"symbol": s, "payload": json.dumps({"side": "long", "legs": legs})}
                for s, legs in self._orders.items()]

    def account_get(self):
        return {"positions": json.dumps(self._positions)}


class _Worker:
    def __init__(self, db):
        self.db = db

    class config_store:  # noqa: N801 — мини-двойник атрибута
        @staticmethod
        def effective():
            return {}


def _reader(tmp_path, worker_db):
    path = str(tmp_path / "scout.db")
    db = DB(db_path=path, owner=True)
    db.scout_control_mark(last_b_boundary_ms=NOW)       # ненулевой курсор скана
    r = ScoutReader(scout_db_path=path, worker_reader=_Worker(worker_db),
                    detector_version="test", producer="test")
    return r, db


def test_synthesis_for_held_without_finding(tmp_path):
    """Скаут монету НЕ отслеживает (0 находок), но позиция живая → снимок СИНТЕЗИРУЕТСЯ:
    график в консоли не пропадает, факт-слой (ордера/позиция) живой; сетки нет → без verified."""
    wdb = _WorkerDB(
        orders_by={"AKEUSDT": [{"level": 0.5, "entry": 0.0016, "qty": 100.0,
                                "filled": False, "order_id": "o1"}]},
        positions=[{"symbol": "AKEUSDT", "side": "Buy", "size": 100.0,
                    "avgPrice": 0.0017, "unrealisedPnl": 1.0}],
    )
    r, _ = _reader(tmp_path, wdb)
    scan_ms, snaps = r.build_snapshots(held=frozenset({"AKEUSDT"}))
    assert scan_ms == NOW
    assert len(snaps) == 1
    s = snaps[0]
    assert s["symbol"] == "AKEUSDT" and s["tf"] == "4h" and s["state"] == "tracking"
    assert s["orders"] and s["position"]["side"] == "Buy"
    assert "verified" not in s             # сетка не посчиталась (нет свечей) — честно без неё
    r.close()


def test_verified_override_for_held_finding(tmp_path, monkeypatch):
    """Находка скаута есть, монета held → уровни ЗАМЕНЯЮТСЯ сеткой движка + verified=true.
    Grid подменён (plumbing); геометрия warm.classify доказана живыми прогонами."""
    wdb = _WorkerDB()
    r, db = _reader(tmp_path, wdb)
    db.scout_findings_put_snapshot(
        [{"symbol": "XUSDT", "status": "tracking", "tf": "4h", "score": 70,
          "A": 1.0, "B": 2.0, "entries": {"0.382": 1.618, "0.5": 1.5, "0.618": 1.382},
          "stop": 1.0}],
        NOW, "4h")
    monkeypatch.setattr(r, "_verified_grid", lambda sym: {
        "A": 8.0, "B": 10.0, "stop": 8.0,
        "entries": {0.382: 9.236, 0.5: 9.0, 0.618: 8.764}})
    _, snaps = r.build_snapshots(held=frozenset({"XUSDT"}))
    (s,) = snaps
    assert s["verified"] is True
    lv = {x["role"]: x["price"] for x in s["levels"]}
    assert lv["A"] == 8.0 and lv["B"] == 10.0 and lv["entry_05"] == 9.0   # сетка ДВИЖКА, не скаута
    r.close()


def test_scout_only_snapshot_untouched_without_held(tmp_path):
    """Без held поведение прежнее: уровни скаута как есть, verified нет (флот/не-динамика чисты)."""
    wdb = _WorkerDB()
    r, db = _reader(tmp_path, wdb)
    db.scout_findings_put_snapshot(
        [{"symbol": "YUSDT", "status": "ready", "tf": "4h", "score": 90,
          "A": 1.0, "B": 2.0, "entries": {"0.382": 1.618, "0.5": 1.5, "0.618": 1.382},
          "stop": 1.0}],
        NOW, "4h")
    _, snaps = r.build_snapshots()
    (s,) = snaps
    assert "verified" not in s
    lv = {x["role"]: x["price"] for x in s["levels"]}
    assert lv["entry_05"] == 1.5                     # оценка скаута нетронута
    r.close()


def test_verified_grid_graceful_on_flat_series(tmp_path):
    """Реальный vendor-путь до конца: короткая серия → None; плоская длинная (нет пробоя) → None.
    Ничего не падает, снимок просто идёт без сетки."""
    wdb = _WorkerDB()
    r, db = _reader(tmp_path, wdb)
    flat10 = [{"time": NOW + i * FOUR_H, "open": 100.0, "high": 101.0,
               "low": 99.0, "close": 100.0, "volume": 1.0} for i in range(10)]
    db.scout_klines_put_many("ZUSDT", "4h", flat10)
    assert r._verified_grid("ZUSDT") is None         # <60 баров
    flat90 = [{"time": NOW + i * FOUR_H, "open": 100.0, "high": 101.0,
               "low": 99.0, "close": 100.0, "volume": 1.0} for i in range(90)]
    db.scout_klines_put_many("ZUSDT", "4h", flat90)
    assert r._verified_grid("ZUSDT") is None         # плоско — warm не находит активного пробоя
    r.close()
