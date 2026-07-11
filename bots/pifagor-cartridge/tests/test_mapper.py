"""Маппер build_monitor→Контракт: чистые функции на синтетических вью-моделях (мок, без БД).

Проверяем приоритет статуса, форму equity, фильтры/курсоры trades/events, разбор detail.
"""

from app import mapper


def _monitor(**over):
    m = {
        "status": {"stale": False, "banner": "normal"},
        "capital": {"equity": 1200.0, "working": 1000.0, "cushion": 200.0,
                    "killswitch_active": False},
        "trades": [],
        "events": [],
    }
    for k, v in over.items():
        m[k] = {**m.get(k, {}), **v} if isinstance(v, dict) else v
    return m


# ── heartbeat.status: приоритет stop_close > pause > stale > running ──────────

def test_status_running():
    assert mapper.heartbeat_status(_monitor(), paused=False) == "running"


def test_status_paused():
    assert mapper.heartbeat_status(_monitor(), paused=True) == "paused"


def test_status_stale_is_error():
    assert mapper.heartbeat_status(_monitor(status={"stale": True}), paused=False) == "error"


def test_status_killswitch_is_stopping_over_paused():
    m = _monitor(capital={"killswitch_active": True})
    assert mapper.heartbeat_status(m, paused=True) == "stopping"   # стоп сильнее паузы


# ── equity ───────────────────────────────────────────────────────────────────

def test_equity_point_shape():
    p = mapper.equity_point(_monitor(), ts_iso="2026-07-11T12:00:00+00:00")
    assert p == {"ts": "2026-07-11T12:00:00+00:00", "equity": 1200.0,
                 "currency": "USDT", "working": 1000.0, "cushion": 200.0}


def test_equity_survives_bad_numbers():
    p = mapper.equity_point(_monitor(capital={"equity": None, "working": "x"}), ts_iso="t")
    assert p["equity"] == 0.0 and p["working"] == 0.0    # битый снимок не роняет телеметрию


# ── trades: маппинг полей, фильтры, курсор ───────────────────────────────────

def _trade(**over):
    row = {"id": 1, "created_ms": 1_700_000_000_000, "symbol": "BTCUSDT", "side": "Sell",
           "qty": 0.01, "closed_pnl": 12.5, "dedup_key": "dk-1", "order_id": "o-1"}
    row.update(over)
    return row


def test_trade_maps_side_and_pnl():
    m = _monitor(trades=[_trade()])
    batch, cursor = mapper.trades_batch(m, after_id=0)
    assert cursor == 1
    (t,) = batch
    assert t["side"] == "sell" and t["exec_id"] == "dk-1" and t["symbol"] == "BTCUSDT"
    assert t["qty"] == 0.01 and t["pnl"] == 12.5
    assert t["ts"].startswith("2023-")                  # created_ms → ISO


def test_trade_long_side_maps_buy():
    m = _monitor(trades=[_trade(side="Buy")])
    (t,), _ = mapper.trades_batch(m, after_id=0)
    assert t["side"] == "buy"


def test_trade_cursor_filters_seen():
    m = _monitor(trades=[_trade(id=5), _trade(id=4, dedup_key="dk-4")])
    batch, cursor = mapper.trades_batch(m, after_id=4)   # id<=4 отсекаются
    assert cursor == 5 and [t["exec_id"] for t in batch] == ["dk-1"]


def test_trade_drops_bad_qty_and_side():
    m = _monitor(trades=[_trade(id=2, qty=0), _trade(id=3, side="?", dedup_key="dk-3")])
    batch, cursor = mapper.trades_batch(m, after_id=0)
    assert batch == [] and cursor == 3                  # курсор двигается, но невалидные не шлём


def test_trade_batch_chronological_order():
    m = _monitor(trades=[_trade(id=3, dedup_key="c"), _trade(id=2, dedup_key="b"),
                         _trade(id=1, dedup_key="a")])  # build_monitor отдаёт новые сверху
    batch, _ = mapper.trades_batch(m, after_id=0)
    assert [t["exec_id"] for t in batch] == ["a", "b", "c"]   # старые первыми


def test_exec_id_fallback_to_id():
    m = _monitor(trades=[_trade(dedup_key=None, order_id=None)])
    (t,), _ = mapper.trades_batch(m, after_id=0)
    assert t["exec_id"] == "ct-1"


def test_trade_no_pnl_key_when_absent():
    m = _monitor(trades=[_trade(closed_pnl=None)])
    (t,), _ = mapper.trades_batch(m, after_id=0)
    assert "pnl" not in t


# ── events: detail-разбор, курсор ────────────────────────────────────────────

def _event(**over):
    row = {"id": 1, "ts": "2026-07-11T12:00:00+00:00", "symbol": "BTCUSDT",
           "event": "entry_filled", "detail": '{"leg": 1}'}
    row.update(over)
    return row


def test_event_json_detail_and_symbol():
    m = _monitor(events=[_event()])
    (e,), cursor = mapper.events_batch(m, after_id=0)
    assert cursor == 1 and e["kind"] == "entry_filled"
    assert e["detail"] == {"leg": 1, "symbol": "BTCUSDT"}


def test_event_plain_text_detail():
    m = _monitor(events=[_event(detail="старт dd>=0.50", symbol="ALL")])
    (e,), _ = mapper.events_batch(m, after_id=0)
    assert e["detail"] == {"text": "старт dd>=0.50"}    # symbol=ALL не приклеиваем


def test_event_cursor_and_order():
    m = _monitor(events=[_event(id=3, event="c"), _event(id=2, event="b"), _event(id=1, event="a")])
    batch, cursor = mapper.events_batch(m, after_id=1)
    assert cursor == 3 and [e["kind"] for e in batch] == ["b", "c"]
