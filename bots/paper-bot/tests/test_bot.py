"""Гвозди на цикл PaperBot: heartbeat-троттлинг, честное исполнение команд (pause держит,
stop_close закрывает+встаёт), ack. Движок реальный (детерминированный), клиент — FakeClient."""

from datetime import UTC, datetime

from app.bot import PaperBot
from app.config import BotConfig
from app.engine import PaperEngine

_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, commands=()):
        self.heartbeats: list = []
        self.equity: list = []
        self.trades: list = []
        self.events: list = []
        self.acks: list = []
        self.commands = list(commands)

    def heartbeat(self, *, status, uptime_s, contract_version):
        self.heartbeats.append({"status": status, "uptime_s": uptime_s})

    def push_equity(self, point):
        self.equity.append(point)

    def push_trades(self, trades):
        if trades:
            self.trades.append(trades)

    def push_events(self, events):
        if events:
            self.events.append(events)

    def next_command(self, *, wait):
        return self.commands.pop(0) if self.commands else {"cmd": "none", "cmd_id": None}

    def ack_command(self, *, cmd_id, result, detail=None):
        self.acks.append({"cmd_id": cmd_id, "result": result, "detail": detail})


def _cfg(heartbeat=30.0) -> BotConfig:
    return BotConfig(
        instance_id="i", instance_token="t", core_url="http://core", seed=7,
        tick_interval_s=1.0, heartbeat_interval_s=heartbeat, poll_wait_s=0,
    )


def _bot(fc, cfg=None) -> PaperBot:
    return PaperBot(fc, PaperEngine(seed=7), cfg or _cfg())


def test_tick_sends_heartbeat_and_equity():
    fc = FakeClient()
    _bot(fc).tick_once(_NOW, mono=0.0)
    assert len(fc.heartbeats) == 1 and fc.heartbeats[0]["status"] == "running"
    assert len(fc.equity) == 1


def test_heartbeat_is_throttled():
    fc = FakeClient()
    bot = _bot(fc, _cfg(heartbeat=30.0))
    bot.tick_once(_NOW, mono=0.0)   # первый — шлём
    bot.tick_once(_NOW, mono=5.0)   # 5с < 30с — не шлём
    assert len(fc.heartbeats) == 1
    bot.tick_once(_NOW, mono=35.0)  # прошло >30с — снова шлём
    assert len(fc.heartbeats) == 2


def test_no_command_no_ack():
    fc = FakeClient()
    assert _bot(fc).tick_once(_NOW, mono=0.0) is False
    assert fc.acks == []


def test_pause_holds_and_acks_ok():
    fc = FakeClient(commands=[{"cmd": "pause", "cmd_id": "c1"}])
    bot = _bot(fc)
    assert bot.tick_once(_NOW, mono=0.0) is False
    assert bot._engine.state == "paused"                 # честно: пауза применена
    assert fc.acks == [{"cmd_id": "c1", "result": "ok", "detail": None}]


def test_resume_acks_ok():
    fc = FakeClient(commands=[{"cmd": "resume", "cmd_id": "c2"}])
    bot = _bot(fc)
    bot._engine.pause()
    bot.tick_once(_NOW, mono=0.0)
    assert bot._engine.state == "running"
    assert fc.acks[0]["result"] == "ok"


def test_stop_close_closes_stands_down_and_acks_ok():
    fc = FakeClient()
    bot = _bot(fc)
    for i in range(20):  # набрать позицию
        bot.tick_once(_NOW, mono=float(i))
    assert bot._engine.position > 0
    fc.commands.append({"cmd": "stop_close", "cmd_id": "c3"})
    should_stop = bot.tick_once(_NOW, mono=100.0)
    assert should_stop is True                           # встаём
    assert bot._engine.state == "stopped"
    assert bot._engine.position == 0                     # позиция закрыта
    assert fc.acks[-1] == {"cmd_id": "c3", "result": "ok", "detail": None}
    # kill_switch доложен событием
    assert any(ev["kind"] == "kill_switch" for batch in fc.events for ev in batch)


def test_unknown_command_acks_error():
    fc = FakeClient(commands=[{"cmd": "backtest", "cmd_id": "c4"}])
    _bot(fc).tick_once(_NOW, mono=0.0)
    assert fc.acks[0]["result"] == "error"
