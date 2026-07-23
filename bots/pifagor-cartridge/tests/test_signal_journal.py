"""Сигнальный журнал (порция №3): деривер против НАСТОЯЩЕГО вендора (урок S7 — не моки).

Сеем worker-БД РЕАЛЬНЫМИ писателями движка (signals_put/fills_put/events_put/closed_trade_put —
те же, что зовёт app/cycle.py) → SignalJournalDeriver → проверяем события Контракта: маппинг
kind/setup_id/data (подписи Куратора П1–П4), курсор без потерь/дублей, пере-дерив после «падения»
(натуральные ключи те же), guard эпохи (fingerprint: строка исчезла/ts разошёлся → parked +
journal_epoch_reset + курсор не движется).
"""

from storage.db import DB

from app.signal_journal import SignalJournalDeriver


class _Client:
    """Захват пушей + программируемый курсор ядра (сеть не нужна)."""

    def __init__(self, cursor=None):
        self.pushed: list[list[dict]] = []
        self.cursor = cursor or {"max_seq": 0, "tables": {}}

    def push_signal_journal(self, events):
        self.pushed.append(list(events))

    def get_signal_journal_cursor(self):
        return self.cursor

    @property
    def flat(self):
        return [e for batch in self.pushed for e in batch]


class _Reader:
    def __init__(self, db):
        self.db = db


def _db(tmp_path) -> DB:
    return DB(db_path=str(tmp_path / "worker.db"), owner=True, database_url="")


def _deriver(db, client=None) -> tuple[SignalJournalDeriver, _Client]:
    c = client or _Client()
    d = SignalJournalDeriver(_Reader(db), c, core_label="BORS", now_ms=lambda: 1_700_000_000_000)
    return d, c


def _seed_life(db) -> None:
    """Полная жизнь сетапа РЕАЛЬНЫМИ писателями: детект → постановка → залив → выход → финал."""
    db.signals_put(symbol="WLFIUSDT", side="long", bar_time=1784808000, a=0.05119, b=0.06494,
                   entry_0382=0.05969, entry_05=0.05807, entry_0618=0.05644, stop=0.05119,
                   tgt_0382=0.06170, tgt_05=0.06864, tgt_0618=0.05969,
                   ts="2026-07-23T08:00:00+00:00")
    db.events_put(symbol="WLFIUSDT", event="setup_placed", detail="3 ноги",
                  ts="2026-07-23T08:00:05+00:00")
    db.fills_put(symbol="WLFIUSDT", side="long", entry_level="0.382", exec_type="entry",
                 requested_price=0.05969, requested_qty=29586, exec_qty=29586,
                 order_link_id="wlfi-ent-0382", order_id="OID-1", ts="2026-07-23T13:04:00+00:00")
    db.events_put(symbol="WLFIUSDT", event="leg_exit", role="tgt", lv=0.382, qty=29586,
                  exit_link="wlfi-tgt", order_id="OID-2", ts="2026-07-23T13:48:00+00:00")
    db.events_put(symbol="WLFIUSDT", event="setup_closed", detail="timeout wait=72",
                  ts="2026-07-23T20:00:00+00:00")
    db.closed_trade_put(created_ms=1784850000000, symbol="WLFIUSDT", side="long", qty=29586,
                        avg_entry=0.05968, avg_exit=0.06174, closed_pnl=60.9, order_id="OID-2")


def test_full_life_derivation(tmp_path):
    """Жизнь сетапа → 6 событий верных kind/setup_id; порядок причинный; конверт полон."""
    db = _db(tmp_path)
    _seed_life(db)
    d, c = _deriver(db)
    d.tick()
    kinds = [e["kind"] for e in c.flat]
    assert kinds == ["setup_detected", "setup_placed", "leg_filled", "leg_exit",
                     "setup_ended", "trade_closed"]
    sid = "WLFIUSDT:1784808000"
    assert all(e["setup_id"] == sid for e in c.flat)          # сквозной id через всю жизнь
    assert [e["seq"] for e in c.flat] == [1, 2, 3, 4, 5, 6]   # порядок повтора
    assert all(e["core"] == "BORS" and e["schema_version"] == 1 for e in c.flat)
    assert all(e["src"]["table"] in ("signals", "fills", "events", "closed_trades")
               for e in c.flat)


def test_detected_data_and_adapter_enrich(tmp_path):
    """П4: сетка из signals как есть; mb/tf — блок adapter (provenance), не от движка."""
    import config as vcfg
    vcfg.strategy.COINS_CONFIG["WLFIUSDT"] = {
        "enabled": True, "mb1": 2.5, "mb2": 4.25, "leverage": 5, "weight": 1.0,
    }
    db = _db(tmp_path)
    _seed_life(db)
    d, c = _deriver(db)
    d.tick()
    det = c.flat[0]["data"]
    assert det["entries"]["0.5"] == 0.05807 and det["stop"] == 0.05119
    assert det["adapter"]["mb1"] == 2.5 and det["adapter"]["provenance"] == "adapter"


def test_leg_filled_requested_not_exec(tmp_path):
    """П3: leg_filled несёт ЗАПРОШЕННЫЕ цены (requested_*), exec не обещаем."""
    db = _db(tmp_path)
    _seed_life(db)
    d, c = _deriver(db)
    d.tick()
    lf = next(e for e in c.flat if e["kind"] == "leg_filled")
    assert lf["data"]["requested_price"] == 0.05969
    assert "exec_price" not in lf["data"]


def test_setup_ended_reason_timeout_from_detail(tmp_path):
    """П2: timeout — НЕ отдельное событие, reason парсится из detail setup_closed."""
    db = _db(tmp_path)
    _seed_life(db)
    d, c = _deriver(db)
    d.tick()
    ended = next(e for e in c.flat if e["kind"] == "setup_ended")
    assert ended["data"]["reason"] == "timeout"


def test_service_catch_all_nothing_dropped(tmp_path):
    """П1: незнакомые события (worker_boot/kill_switch_stop/orphan) → service с raw, не дроп."""
    db = _db(tmp_path)
    db.events_put(symbol="ALL", event="worker_boot", detail="boot_ms=1")
    db.events_put(symbol="WLFIUSDT", event="orphan_position", detail="found")
    db.events_put(symbol="ALL", event="kill_switch_stop", detail="dd")
    d, c = _deriver(db)
    d.tick()
    assert [e["kind"] for e in c.flat] == ["service"] * 3
    assert {e["data"]["raw"] for e in c.flat} == {"worker_boot", "orphan_position",
                                                  "kill_switch_stop"}


def test_cursor_no_dup_no_loss(tmp_path):
    """Курсор: второй тик без новых строк → 0 пушей; новая строка → ровно одно новое событие."""
    db = _db(tmp_path)
    _seed_life(db)
    d, c = _deriver(db)
    d.tick()
    n = len(c.flat)
    d.tick()
    assert len(c.flat) == n                       # дублей нет
    db.events_put(symbol="WLFIUSDT", event="warm_apply", detail="csv")
    d.tick()
    assert len(c.flat) == n + 1 and c.flat[-1]["data"]["raw"] == "warm_apply"


def test_rederive_same_natural_keys(tmp_path):
    """Пере-дерив после «падения» (свежий деривер, пустой курсор ядра) даёт ТЕ ЖЕ натуральные
    ключи (src.table, src.id) → ядро DO NOTHING (вариант A: корректность без состояния)."""
    db = _db(tmp_path)
    _seed_life(db)
    d1, c1 = _deriver(db)
    d1.tick()
    d2, c2 = _deriver(db)                          # «упал и перезапустился», курсоры с нуля
    d2.tick()
    keys1 = [(e["src"]["table"], e["src"]["id"]) for e in c1.flat]
    keys2 = [(e["src"]["table"], e["src"]["id"]) for e in c2.flat]
    assert keys1 == keys2


def test_seq_resumes_from_core(tmp_path):
    """seq продолжается от max_seq ядра (порядок повтора не рвётся)."""
    db = _db(tmp_path)
    db.events_put(symbol="ALL", event="worker_boot", detail=None)
    d, c = _deriver(db, _Client(cursor={"max_seq": 41, "tables": {}}))
    d.tick()
    assert c.flat[0]["seq"] == 42


def test_epoch_reset_fingerprint_missing_row(tmp_path):
    """Guard эпохи: курсор ядра указывает id=100, в БД его НЕТ (сброс) → parked +
    journal_epoch_reset (src.table=adapter), деривация СТОИТ, старые id не пере-пушатся."""
    db = _db(tmp_path)
    db.events_put(symbol="ALL", event="worker_boot", detail=None)   # свежая эпоха: MAX(id)=1
    cur = {"max_seq": 500, "tables": {"events": {"src_id": 100, "ts": "2026-07-20T00:00:00+00:00"}}}
    d, c = _deriver(db, _Client(cursor=cur))
    d.tick()
    assert len(c.flat) == 1
    reset = c.flat[0]
    assert reset["kind"] == "service" and reset["data"]["raw"] == "journal_epoch_reset"
    assert reset["src"]["table"] == "adapter"
    d.tick()
    assert len(c.flat) == 1                        # parked: ничего больше не деривится


def test_epoch_reset_fingerprint_ts_mismatch(tmp_path):
    """Guard эпохи: id существует, но ts строки РАЗОШЁЛСЯ с сохранённым (быстрый перезалив
    обогнал курсор — усиление Куратора) → тоже parked."""
    db = _db(tmp_path)
    rid = db.events_put(symbol="ALL", event="worker_boot", detail=None,
                        ts="2026-07-23T09:00:00+00:00")
    cur = {"max_seq": 7, "tables": {"events": {"src_id": rid, "ts": "2026-07-20T00:00:00+00:00"}}}
    d, c = _deriver(db, _Client(cursor=cur))
    d.tick()
    assert [e["data"].get("raw") for e in c.flat] == ["journal_epoch_reset"]


def test_epoch_ok_resumes_cursor(tmp_path):
    """Fingerprint сошёлся → курсор резюмится, старые строки НЕ пере-пушатся, новые идут."""
    db = _db(tmp_path)
    rid = db.events_put(symbol="ALL", event="worker_boot", detail=None,
                        ts="2026-07-23T09:00:00+00:00")
    d0, c0 = _deriver(db)
    d0.tick()                                       # узнаём канонический ts события
    stored_ts = c0.flat[0]["ts"]
    cur = {"max_seq": 1, "tables": {"events": {"src_id": rid, "ts": stored_ts}}}
    d, c = _deriver(db, _Client(cursor=cur))
    db.events_put(symbol="ALL", event="idle_gap", detail=None)
    d.tick()
    assert [e["data"]["raw"] for e in c.flat] == ["idle_gap"]   # только новая строка
    assert c.flat[0]["seq"] == 2


def test_fill_before_observation_unknown_setup(tmp_path):
    """Залив ДО нашего наблюдения (сигнал за курсором): setup_id = symbol:unknown, не падаем."""
    db = _db(tmp_path)
    db.fills_put(symbol="ZAMAUSDT", side="long", entry_level="0.5", exec_type="entry",
                 requested_price=0.048, requested_qty=100)
    d, c = _deriver(db)
    d.tick()
    assert c.flat[0]["setup_id"] == "ZAMAUSDT:unknown"


def test_close_all_broadcast_is_service(tmp_path):
    """close_all с symbol=ALL — широковещательное: одного сетапа нет → service (П1, не дроп)."""
    db = _db(tmp_path)
    db.events_put(symbol="ALL", event="close_all", detail="pause")
    d, c = _deriver(db)
    d.tick()
    assert c.flat[0]["kind"] == "service" and c.flat[0]["data"]["raw"] == "close_all"
