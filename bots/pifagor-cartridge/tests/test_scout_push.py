"""Тест триггера scout-пуша в bot._push_scout (#52 + RED-фикс ревью): пушим на НОВЫЙ scan_ts,
скипаем тот же, шлём пустой набор на новом скане (replace). Курсор — scout_control (не meta)."""

from app.bot import PifagorCartridge
from app.config import CartridgeConfig
from app.scout_reader import ScoutReader


class FakeClient:
    def __init__(self):
        self.scouts = []

    def heartbeat(self, **k):
        pass

    def push_equity(self, p):
        pass

    def push_trades(self, t):
        pass

    def push_events(self, e):
        pass

    def push_scout(self, snaps):
        self.scouts.append(snaps)

    def next_command(self, *, wait):
        return {"cmd": "none", "cmd_id": None}

    def ack_command(self, **k):
        pass


class FakeWorker:
    def snapshot(self, **k):
        return {}

    def is_paused(self):
        return False


class FakeScout:
    def __init__(self):
        self.ret = (0, [])

    def build_snapshots(self):
        return self.ret


def _cfg():
    return CartridgeConfig(
        instance_id="i", instance_token="t", core_url="http://c", tick_interval_s=5,
        heartbeat_interval_s=30, poll_wait_s=25, telemetry_retries=1, backoff_base_s=0.1,
        backoff_cap_s=1, scout_interval_s=0,  # 0 → проверяем каждый тик
    )


def _bot(client, scout):
    return PifagorCartridge(client, FakeWorker(), _cfg(), scout_reader=scout)


def test_pushes_on_new_scan_skips_same():
    c, sc = FakeClient(), FakeScout()
    bot = _bot(c, sc)
    sc.ret = (100, [{"symbol": "BTCUSDT"}])
    bot._push_scout(1.0)                 # первый скан → push
    bot._push_scout(2.0)                 # тот же scan_ms=100 → skip (не долбим ядро)
    assert len(c.scouts) == 1
    sc.ret = (200, [])                   # НОВЫЙ скан, все сетапы умерли
    bot._push_scout(3.0)                 # пушим пустой (replace: ядро чистит)
    assert len(c.scouts) == 2
    assert c.scouts[1] == []


def test_no_reader_noop():
    c = FakeClient()
    bot = PifagorCartridge(c, FakeWorker(), _cfg())  # scout_reader=None (флот)
    bot._push_scout(1.0)
    assert c.scouts == []


def test_scan_ms_zero_no_push():
    c, sc = FakeClient(), FakeScout()
    bot = _bot(c, sc)
    sc.ret = (0, [])                     # скаут ещё не сканировал (нет курсора)
    bot._push_scout(1.0)
    assert c.scouts == []


# ── _scan_cursor: last_a_ms исключён (#54) — Этап A (без находок) не триггерит пуш ──

class _FakeScoutDB:
    def __init__(self, ctrl):
        self._ctrl = ctrl

    def scout_control_get(self):
        return self._ctrl


def _reader(ctrl):
    r = object.__new__(ScoutReader)      # обходим тяжёлый __init__ (вендор/DB не нужны)
    r.scout_db = _FakeScoutDB(ctrl)
    return r


def test_scan_cursor_stage_a_alone_no_advance():
    # только Этап A (last_a_ms=сейчас), Этапа B ещё не было → курсор 0 (пуш НЕ триггерится)
    r = _reader({"last_a_ms": 9_000, "last_b_boundary_ms": 0, "scan_now_ack_ms": 0})
    assert r._scan_cursor() == 0


def test_scan_cursor_stage_b_advances_below_last_a():
    # Этап B на границе 8_000 при более позднем last_a_ms=9_000 → курсор 8_000 (двигает B, не A)
    r = _reader({"last_a_ms": 9_000, "last_b_boundary_ms": 8_000, "scan_now_ack_ms": 0})
    assert r._scan_cursor() == 8_000


def test_scan_cursor_scan_now_button():
    # кнопка «Сканировать сейчас» (scan_now_ack_ms) двигает курсор
    r = _reader({"last_a_ms": 0, "last_b_boundary_ms": 0, "scan_now_ack_ms": 5_000})
    assert r._scan_cursor() == 5_000
