"""engine_state — компакт движкового состояния для карточки бота (S7). Из build_monitor."""

from app.mapper import engine_state


def _monitor(**over):
    m = {
        "status": {"stale": False, "banner": "живая торговля"},
        "capital": {"equity": 20000, "peak_equity": 21000, "dd_pct": 4.7, "state": "running",
                    "killswitch_active": False, "alarm_active": False,
                    "unrealised_pnl": 12.5, "realised_pnl": -3.0, "open_count": 1},
        "positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": 0.1,
                       "avgPrice": 60000, "unrealisedPnl": 12.5}],
        "pending": [{"symbol": "BTCUSDT", "payload": {"side": "buy",
                     "legs": [{"order_id": "o1", "entry": 59000, "qty": 0.1, "filled": False}]}}],
        "trades": [{"symbol": "ETHUSDT", "side": "Sell", "qty": 1.0,
                    "closed_pnl": 5.0, "created_ms": 1_700_000_000_000}],
        "events": [{"event": "entry", "ts": "2026-07-17T00:00:00Z", "detail": "x"}],
    }
    m.update(over)
    return m


def test_engine_state_maps_all():
    es = engine_state(_monitor())
    assert es["status"]["state"] == "running" and es["status"]["kill_switch"] is False
    assert es["capital"]["equity"] == 20000 and es["capital"]["open_count"] == 1
    p = es["positions"][0]
    assert p["symbol"] == "BTCUSDT" and p["avg_px"] == 60000 and p["live_pnl"] == 12.5
    o = es["orders"][0]
    assert o["symbol"] == "BTCUSDT" and o["px"] == 59000 and o["qty"] == 0.1
    assert o["status"] == "pending"
    assert es["trades"][0]["pnl"] == 5.0 and es["events"][0]["kind"] == "entry"


def test_engine_state_flat_hides_zero_positions():
    es = engine_state(_monitor(positions=[{"symbol": "X", "size": 0}], pending=[]))
    assert es["positions"] == [] and es["orders"] == []


def test_engine_state_killswitch_implies_stopping():
    es = engine_state(_monitor(capital={"killswitch_active": True, "equity": 1}))
    assert es["status"]["kill_switch"] is True and es["status"]["state"] == "stopping"


def test_engine_state_empty_monitor_safe():
    es = engine_state({})
    assert es["positions"] == [] and es["orders"] == [] and es["capital"]["open_count"] == 0
