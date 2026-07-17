"""Интеграция scan_now с НАСТОЯЩИМ вендором (регресс живого бага Разведка-стола).

Живой Галахад показал: `scout_control_mark(scan_now_ms=…)` — тихий no-op (mark = «скаут-сторона»
с whitelist БЕЗ scan_now_ms, db.py:1254-1257) → ack ok, а Этап B не стартовал. Прежний тест мокал
scout_db и контракт вендора не ловил. Здесь — настоящий storage.db.DB (два соединения на одном
sqlite-файле, как в проде: скаут-владелец + адаптер) и настоящий scout.main.decide."""

from app.scout_reader import ScoutReader


def _reader(db_path: str) -> ScoutReader:
    # worker_reader для scan_now не нужен (он про ордера/конфиг движка) — заглушка
    return ScoutReader(
        scout_db_path=db_path, worker_reader=object(),
        detector_version="test", producer="test",
    )


def test_scan_now_lands_in_vendor_control_and_triggers_button(tmp_path):
    """Адаптер пишет кнопку → скаут-сторона ВИДИТ её и decide() даёт ('B','button')."""
    from scout.main import decide
    from storage.db import DB

    path = str(tmp_path / "scout.db")
    scout_side = DB(db_path=path, owner=True)            # скаут: владелец схемы (как в проде)
    scout_side.scout_control_mark(last_a_ms=1_000)       # список откалиброван (не bootstrap)

    _reader(path).scan_now(now_ms=5_000)                 # адаптер: ВТОРОЕ соединение, как в проде

    ctrl = scout_side.scout_control_get()
    assert ctrl["scan_now_ms"] == 5_000, "кнопка не легла в scout_control — регресс живого бага"
    assert decide(ctrl, 6_000, tf="4h", auto=True, cal_hour=5, list_present=True) == ("B", "button")


def test_vendor_mark_silently_drops_scan_now_ms(tmp_path):
    """Страж контракта вендора: mark НЕ канал кнопки (молча дропает scan_now_ms). Если вендорский
    снимок однажды сменит контракт — тест скажет, и scan_now() надо будет пересмотреть."""
    from storage.db import DB

    db = DB(db_path=str(tmp_path / "scout.db"), owner=True)
    db.scout_control_mark(scan_now_ms=7_000)             # «скаут-сторона»: чужой ключ игнорируется
    assert db.scout_control_get()["scan_now_ms"] == 0


def test_force_recalibrate_makes_vendor_bootstrap(tmp_path):
    """dozor_apply → перекалибровка: сброс last_a_ms → decide() даёт Этап A даже при ЖИВОМ списке
    (иначе новые пороги отбора не пересобрали бы scout_list). Регресс живого бага «нет разницы»."""
    from scout.main import decide
    from storage.db import DB

    path = str(tmp_path / "scout.db")
    scout_side = DB(db_path=path, owner=True)
    scout_side.scout_control_mark(last_a_ms=9_999)  # список откалиброван
    kw = {"tf": "4h", "auto": False, "cal_hour": 9, "list_present": True}

    # до сброса: живой список → decide пропускает bootstrap (Этап B/idle, не A)
    assert decide(scout_side.scout_control_get(), 10_000, **kw)[0] != "A"

    _reader(path).force_recalibrate()  # адаптер: сброс last_a_ms=0

    ctrl = scout_side.scout_control_get()
    assert ctrl["last_a_ms"] == 0, "last_a_ms не сброшен — регресс: настройки не перекалибруют"
    assert decide(ctrl, 10_000, **kw) == ("A", "bootstrap")


def test_scan_now_ack_flow_roundtrip(tmp_path):
    """Полный круг кнопки: request → decide=button → скаут ачит → decide=idle (single-shot)."""
    from scout.main import decide
    from storage.db import DB

    path = str(tmp_path / "scout.db")
    scout_side = DB(db_path=path, owner=True)
    scout_side.scout_control_mark(last_a_ms=1_000)
    _reader(path).scan_now(now_ms=5_000)

    ctrl = scout_side.scout_control_get()
    kw = {"tf": "4h", "auto": False, "cal_hour": 9, "list_present": True}
    assert decide(ctrl, 6_000, **kw) == ("B", "button")
    scout_side.scout_control_mark(scan_now_ack_ms=ctrl["scan_now_ms"])  # как main.py:198
    ctrl2 = scout_side.scout_control_get()
    assert decide(ctrl2, 7_000, **kw)[0] is None
