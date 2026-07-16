"""Цикл PifagorCartridge: каденция heartbeat, честные команды, поведение курсоров при 4xx.

Клиент/ридер — фейки (без сети/БД). Проверяем контрактное поведение цикла, не транспорт.
"""

from datetime import UTC, datetime

import pytest

from app.bot import PifagorCartridge
from app.client import PayloadTooLarge, PermanentError, TransientError
from app.config import CartridgeConfig

NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _cfg(**over):
    base = dict(instance_id="i", instance_token="t", core_url="http://c",
                tick_interval_s=5.0, heartbeat_interval_s=30.0, poll_wait_s=0,
                telemetry_retries=0, backoff_base_s=0.0, backoff_cap_s=0.0)
    base.update(over)
    return CartridgeConfig(**base)


class FakeClient:
    def __init__(self):
        self.heartbeats, self.equities, self.trades, self.events, self.acks = [], [], [], [], []
        self.cmds: list[dict] = []
        self.trade_errors: list[Exception | None] = []   # по одному на вызов push_trades
        self.hb_errors: list[Exception | None] = []       # по одному на вызов heartbeat
        self.hb_attempts = 0

    def heartbeat(self, *, status, uptime_s, contract_version):
        self.hb_attempts += 1
        if self.hb_errors:
            err = self.hb_errors.pop(0)
            if err is not None:
                raise err
        self.heartbeats.append(status)

    def push_equity(self, point):
        self.equities.append(point)

    def push_trades(self, trades):
        if self.trade_errors:
            err = self.trade_errors.pop(0)
            if err is not None:
                raise err
        self.trades.append(list(trades))

    def push_events(self, events):
        self.events.append(list(events))

    def next_command(self, *, wait):
        return self.cmds.pop(0) if self.cmds else {"cmd": "none", "cmd_id": None}

    def ack_command(self, *, cmd_id, result, detail=None):
        self.acks.append({"cmd_id": cmd_id, "result": result, "detail": detail})


class FakeReader:
    def __init__(self, monitor=None):
        self.monitor = monitor or {"status": {"stale": False}, "capital": {
            "equity": 100.0, "working": 80.0, "cushion": 20.0, "killswitch_active": False},
            "trades": [], "events": []}
        self.paused = False
        self.calls: list[str] = []
        self.stop_close_exc: Exception | None = None   # леджер не засеян → латч не встал

    def snapshot(self, *, now_ms=None):
        return self.monitor

    def is_paused(self):
        return self.paused

    def pause(self):
        self.calls.append("pause")
        self.paused = True

    def resume(self):
        self.calls.append("resume")
        self.paused = False

    def stop_close(self):
        self.calls.append("stop_close")
        if self.stop_close_exc is not None:
            raise self.stop_close_exc


def _bot(client, reader, cfg=None):
    return PifagorCartridge(client, reader, cfg or _cfg(), sleep=lambda _s: None)


# ── каденция heartbeat ───────────────────────────────────────────────────────

def test_heartbeat_first_tick_then_throttled():
    c, r = FakeClient(), FakeReader()
    bot = _bot(c, r)
    bot.tick_once(NOW, mono=0.0)          # первый → heartbeat
    bot.tick_once(NOW, mono=10.0)         # в окне 30с → нет heartbeat
    bot.tick_once(NOW, mono=40.0)         # прошло ≥30с → heartbeat
    assert c.heartbeats == ["running", "running"]
    assert len(c.equities) == 3           # equity — каждый тик


# ── команды: честная трансляция в контролы ───────────────────────────────────

def test_pause_command_calls_reader_and_acks():
    c, r = FakeClient(), FakeReader()
    c.cmds = [{"cmd": "pause", "cmd_id": "p1"}]
    assert _bot(c, r).tick_once(NOW, 0.0) is False
    assert r.calls == ["pause"] and c.acks == [{"cmd_id": "p1", "result": "ok", "detail": None}]


def test_resume_command():
    c, r = FakeClient(), FakeReader()
    r.paused = True
    c.cmds = [{"cmd": "resume", "cmd_id": "r1"}]
    _bot(c, r).tick_once(NOW, 0.0)
    assert r.calls == ["resume"] and c.acks[0]["result"] == "ok"


def test_stop_close_latches_stands_and_acks():
    c, r = FakeClient(), FakeReader()
    c.cmds = [{"cmd": "stop_close", "cmd_id": "s1"}]
    should_stop = _bot(c, r).tick_once(NOW, 0.0)
    assert should_stop is True
    assert r.calls == ["stop_close"]
    assert "stopping" in c.heartbeats                 # немедленный видимый стоп
    assert c.acks == [{"cmd_id": "s1", "result": "ok", "detail": None}]


def test_unknown_command_acked_error():
    c, r = FakeClient(), FakeReader()
    c.cmds = [{"cmd": "frobnicate", "cmd_id": "x1"}]
    _bot(c, r).tick_once(NOW, 0.0)
    assert c.acks[0]["result"] == "error" and "unknown" in c.acks[0]["detail"]["reason"]
    assert r.calls == []


def test_none_command_no_ack():
    c, r = FakeClient(), FakeReader()
    _bot(c, r).tick_once(NOW, 0.0)
    assert c.acks == []


# ── курсоры trades при 4xx ───────────────────────────────────────────────────

def _monitor_with_trades(trades):
    return {"status": {"stale": False}, "trades": trades, "events": [],
            "capital": {"equity": 1.0, "working": 1.0, "cushion": 0.0, "killswitch_active": False}}


def _trade_row(i, dk):
    return {"id": i, "created_ms": 1_700_000_000_000 + i, "symbol": "X",
            "side": "Buy", "qty": 1.0, "closed_pnl": None, "dedup_key": dk}


def _reader_with_trade():
    return FakeReader(_monitor_with_trades([_trade_row(7, "dk7")]))


def test_transient_giveup_does_not_advance_cursor():
    c, r = FakeClient(), _reader_with_trade()
    c.trade_errors = [TransientError("503", status=503)]   # первый push_trades транзиентно падает
    bot = _bot(c, r)
    bot.tick_once(NOW, 0.0)                # give-up (retries=0) → курсор НЕ двигается
    bot.tick_once(NOW, 1.0)               # тот же трейд шлётся снова (at-least-once)
    assert len(c.trades) == 1 and c.trades[0][0]["exec_id"] == "dk7"


def test_permanent_advances_cursor():
    c, r = FakeClient(), _reader_with_trade()
    c.trade_errors = [PermanentError("422", status=422)]   # перманентный дроп
    bot = _bot(c, r)
    bot.tick_once(NOW, 0.0)                # дроп + курсор ДВИГАЕТСЯ
    bot.tick_once(NOW, 1.0)               # трейд уже за курсором → не шлётся
    assert c.trades == []                 # ничего не доставлено (дропнут навсегда)


def test_413_splits_batch():
    c = FakeClient()
    r = FakeReader(_monitor_with_trades([_trade_row(1, "dk1"), _trade_row(2, "dk2")]))
    c.trade_errors = [PayloadTooLarge("413", status=413)]  # цельный батч велик → дробим пополам
    _bot(c, r).tick_once(NOW, 0.0)
    # после дробления оба элемента доставлены отдельными пушами
    delivered = [t["exec_id"] for batch in c.trades for t in batch]
    assert sorted(delivered) == ["dk1", "dk2"]


# ── ревью-фиксы ──────────────────────────────────────────────────────────────

def test_stop_close_unseeded_no_ack_no_stand():
    """Латч не встал (леджер не засеян) → reader.stop_close рейзит → НЕ ack'аем ok, НЕ встаём."""
    c, r = FakeClient(), FakeReader()
    r.stop_close_exc = RuntimeError("kill-switch не защёлкнулся")
    c.cmds = [{"cmd": "stop_close", "cmd_id": "s1"}]
    with pytest.raises(RuntimeError):
        _bot(c, r).tick_once(NOW, 0.0)      # рейз пробивает наверх (run() поймает best-effort)
    assert c.acks == []                      # ложного ack ok нет → команда останется липкой


def test_failed_heartbeat_not_throttled_retries_next_tick():
    """Провал heartbeat НЕ двигает каденцию → следующий тик ретраит (не ждём полный интервал)."""
    c, r = FakeClient(), FakeReader()
    c.hb_errors = [TransientError("503", status=503)]   # первый heartbeat падает транзиентно
    bot = _bot(c, r)
    bot.tick_once(NOW, 0.0)                 # heartbeat #1 (провал) — каденция НЕ сдвинута
    bot.tick_once(NOW, 1.0)                 # 1с < 30с, но каденция не сдвигалась → heartbeat #2
    assert c.hb_attempts == 2 and c.heartbeats == ["running"]   # вторая попытка доставлена


def test_scroll_gap_warns_on_big_cursor_jump(caplog):
    """Курсор прыгнул больше окна build_monitor → WARNING о возможном пропуске (ревью #1)."""
    c = FakeClient()
    # одна сделка с id ЗА окном (250 > TRADES_WINDOW=200), курсор 0 → прыжок 250 > 200
    r = FakeReader(_monitor_with_trades([_trade_row(250, "dk250")]))
    with caplog.at_level("WARNING", logger="mfc.pifagor-cartridge"):
        _bot(c, r).tick_once(NOW, 0.0)
    assert any("ВОЗМОЖЕН ПРОПУСК" in rec.message for rec in caplog.records)


# ── команда screener_run (С7-2б): отдельный процесс + ack ─────────────────────

def test_screener_run_launches_process_and_acks(monkeypatch):
    import subprocess
    c, r = FakeClient(), FakeReader()
    launched = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda args, *a, **k: launched.setdefault("args", args))
    c.cmds = [{"cmd": "screener_run", "cmd_id": "sc1",
               "payload": {"run_id": "RID", "params": {"k": 2.0, "universe_max": 80}}}]
    assert _bot(c, r).tick_once(NOW, 0.0) is False
    assert c.acks == [{"cmd_id": "sc1", "result": "ok", "detail": None}]
    a = launched["args"]
    assert "--push" in a and "app.screener" in a
    assert a[a.index("--run-id") + 1] == "RID"
    assert a[a.index("--k") + 1] == "2.0"
    assert a[a.index("--universe-max") + 1] == "80"


def test_screener_run_no_run_id_acks_without_spawn(monkeypatch):
    import subprocess
    c, r = FakeClient(), FakeReader()
    calls = {"n": 0}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    c.cmds = [{"cmd": "screener_run", "cmd_id": "sc2", "payload": {}}]
    _bot(c, r).tick_once(NOW, 0.0)
    assert c.acks == [{"cmd_id": "sc2", "result": "ok", "detail": None}]
    assert calls["n"] == 0
