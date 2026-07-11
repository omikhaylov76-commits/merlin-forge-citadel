"""PARITY-тест (Куратор #10): адаптерная телеметрия == build_monitor(@b75bd17) на одном состоянии.

Гарантия faithfulness на уровне цифр: картридж показывает ТО ЖЕ, что родной дашборд Пифагора.
Использует РЕАЛЬНЫЙ вендоренный build_monitor на засеянной SQLite-БД (не мок). Требует вендоренные
зависимости (pandas/numpy — тянет граф state→reconcile→strategy.engine). Путь вендора — из conftest.
"""

import json

import pytest

# вендоренный снимок Пифагора (путь добавлен conftest)
from dashboard.viewmodel import build_monitor
from risk_capital import killswitch
from risk_capital.ledger import Ledger
from state.capital import CapitalStore
from state.config import ConfigStore
from state.store import StateStore
from storage.db import DB

from app import mapper
from app.reader import PifagorReader

_NOW_MS = 1_700_000_000_000


@pytest.fixture
def seeded_db(tmp_path):
    """Owner-БД (схема) + состояние: капитал, кривая, сделка, события, heartbeat."""
    db_path = str(tmp_path / "pif.db")
    owner = DB(db_path=db_path, owner=True)
    Ledger(CapitalStore(owner)).seed(1000.0, 200.0)
    owner.heartbeat_put(ts_ms=_NOW_MS, active_setups=0)          # свежий → не stale
    owner.equity_history_put(ts_ms=_NOW_MS - 3_600_000, total_equity=1150.0)
    owner.equity_history_put(ts_ms=_NOW_MS, total_equity=1200.0)
    owner.closed_trade_put(created_ms=_NOW_MS, symbol="BTCUSDT", side="Sell", qty=0.01,
                           avg_entry=50000.0, avg_exit=51250.0, closed_pnl=12.5, order_id="o-1")
    owner.events_put(symbol="BTCUSDT", event="entry_filled", detail=json.dumps({"leg": 1}))
    return db_path


def test_reader_snapshot_equals_direct_build_monitor(seeded_db):
    """Ридер строит сторы КАК дашборд → его снимок побитово равен прямому build_monitor."""
    ref_db = DB(db_path=seeded_db, owner=False)
    ref = build_monitor(ref_db, capital_store=CapitalStore(ref_db),
                        config_store=ConfigStore(ref_db), state_store=StateStore(ref_db),
                        now_ms=_NOW_MS, prices=None)
    snap = PifagorReader(db_path=seeded_db).snapshot(now_ms=_NOW_MS)
    assert snap["capital"] == ref["capital"]                    # equity/working/cushion/dd/kill
    assert snap["equity_curve"] == ref["equity_curve"]
    assert snap["trades"] == ref["trades"]
    assert snap["events"] == ref["events"]
    assert snap["status"]["stale"] == ref["status"]["stale"]


def test_mapper_equity_matches_dashboard_number(seeded_db):
    """equity в телеметрии Контракта == equity родного монитора (без искажения)."""
    snap = PifagorReader(db_path=seeded_db).snapshot(now_ms=_NOW_MS)
    point = mapper.equity_point(snap, ts_iso="2026-01-01T00:00:00+00:00")
    assert point["equity"] == snap["capital"]["equity"]
    assert point["working"] == snap["capital"]["working"]
    assert point["cushion"] == snap["capital"]["cushion"]


def test_mapper_trades_and_events_faithful(seeded_db):
    snap = PifagorReader(db_path=seeded_db).snapshot(now_ms=_NOW_MS)
    trades, _ = mapper.trades_batch(snap, after_id=0)
    assert len(trades) == 1
    (t,) = trades
    assert t["side"] == "sell" and t["symbol"] == "BTCUSDT"
    assert t["pnl"] == 12.5 and t["qty"] == 0.01
    events, _ = mapper.events_batch(snap, after_id=0)
    assert any(e["kind"] == "entry_filled" and e["detail"].get("leg") == 1 for e in events)


def test_controls_hit_real_engine_mechanisms(seeded_db):
    """pause виден через effective(); stop_close виден через killswitch.is_halted (тот же латч)."""
    r = PifagorReader(db_path=seeded_db)
    r.pause()
    assert r.config_store.effective()["PAUSE_ENABLED"] is True   # cycle читает на старте 4h-цикла
    r.resume()
    assert r.config_store.effective()["PAUSE_ENABLED"] is False
    r.stop_close()
    assert killswitch.is_halted(r.capital_store) is True         # тот же гейт, что в app/cycle.py
    assert r.snapshot(now_ms=_NOW_MS)["capital"]["killswitch_active"] is True
