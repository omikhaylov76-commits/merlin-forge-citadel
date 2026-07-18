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
             dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
             # ADR-0020: критерии из файла (по умолчанию файла нет → провайдер на ген-дефолтах)
             dynamic_criteria_path=str(tmp_path / "dynamic_criteria.json"),
             dynamic_min_score=0, dynamic_fresh_bars=0)
    d.update(kw)
    fs = _FakeScout()
    return DynamicUniverse(types.SimpleNamespace(**d), fs), fs


def _write_criteria(tmp_path, **crit):
    """Записать файл-критерии (как это делает re-fetch) — провайдер читает его живьём."""
    (tmp_path / "dynamic_criteria.json").write_text(json.dumps(crit))


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


def test_min_score_filter(tmp_path):
    """Канал ADR-0020: min_score отсекает низкоскоровые и без-скора кандидатов ПОВЕРХ дозора."""
    dv, fs = _mk(tmp_path)
    _write_criteria(tmp_path, min_score=50, stack_max=3, fresh_bars=0)
    fs.data = (1000, [{"symbol": "AAAUSDT", "tf": "4h", "state": "ready", "score": 80},
                      {"symbol": "BBBUSDT", "tf": "4h", "state": "ready", "score": 30},
                      {"symbol": "CCCUSDT", "tf": "4h", "state": "ready", "score": None}])
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AAAUSDT"}   # 30<50 и None отсеяны


def test_fresh_bars_filter(tmp_path):
    """ADR-0020: fresh_bars отсекает старые сетапы (bars_since_anchor > порога)."""
    dv, fs = _mk(tmp_path)
    _write_criteria(tmp_path, min_score=0, stack_max=3, fresh_bars=48)
    fs.data = (1000, [
        {"symbol": "AAAUSDT", "state": "ready", "score": 80, "bars_since_anchor": 10},
        {"symbol": "BBBUSDT", "state": "ready", "score": 80, "bars_since_anchor": 100}])
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AAAUSDT"}   # 100>48 отсеян, 10 прошёл


def test_cap_shrink_no_evict(tmp_path):
    """EDIT 2: сжатие капа на живую НЕ выгоняет (убытие), добора нет, кап честен."""
    dv, fs = _mk(tmp_path)                              # cfg cap=3
    full = [{"symbol": f"C{i}USDT", "state": "ready", "score": 90 - i} for i in range(3)]
    fs.data = (1000, full)
    dv.tick(2.0)
    assert dv.view()["count"] == 3
    _write_criteria(tmp_path, min_score=0, stack_max=1, fresh_bars=0)   # Оператор сжал 3→1 на живую
    fs.data = (2000, full)                              # те же 3 ещё в печке
    dv.tick(3.0)
    v = dv.view()
    assert v["count"] == 3 and v["cap"] == 1            # никто не выгнан, кап честен (3·кап1)
    fs.data = (3000, [{"symbol": "NEWUSDT", "state": "ready", "score": 99}, *full])
    dv.tick(4.0)
    assert "NEWUSDT" not in {i["symbol"] for i in dv.view()["items"]}   # добора нет (стек ≥ кап)


def test_criteria_read_live(tmp_path):
    """ADR-0020 D1: критерии читаются каждый скан — смена файла между тиками без рестарта."""
    dv, fs = _mk(tmp_path)
    _write_criteria(tmp_path, min_score=0, stack_max=3, fresh_bars=0)
    fs.data = (1000, [{"symbol": "LOWUSDT", "tf": "4h", "state": "ready", "score": 40}])
    dv.tick(2.0)
    assert "LOWUSDT" in {i["symbol"] for i in dv.view()["items"]}       # порог 0 → прошёл
    _write_criteria(tmp_path, min_score=50, stack_max=3, fresh_bars=0)  # порог поднят на живую
    fs.data = (2000, [{"symbol": "LOWUSDT", "tf": "4h", "state": "ready", "score": 40}])
    dv.tick(3.0)                                        # score40<50 → не кандидат → missed=1
    fs.data = (3000, [{"symbol": "LOWUSDT", "tf": "4h", "state": "ready", "score": 40}])
    dv.tick(4.0)                                        # missed=2 ≥ exit → вышел
    assert "LOWUSDT" not in {i["symbol"] for i in dv.view()["items"]}


def test_stack_max_capped(tmp_path):
    """Предохранитель держится и когда stack_max пришёл огромным (env-путь мимо валидации ядра)."""
    dv, fs = _mk(tmp_path)
    _write_criteria(tmp_path, min_score=0, stack_max=100000, fresh_bars=0)
    fs.data = (1000, [{"symbol": f"C{i}USDT", "state": "ready", "score": 200 - i}
                      for i in range(120)])
    dv.tick(2.0)
    assert dv.view()["cap"] == 100 and dv.view()["count"] == 100   # кламп 100, не 100000


def test_fresh_bars_keeps_anchorless_forming(tmp_path):
    """fresh_bars НЕ режет forming: нет bars_since_anchor → свежесть не определена → пропускаем."""
    dv, fs = _mk(tmp_path)
    _write_criteria(tmp_path, min_score=0, stack_max=3, fresh_bars=48)
    fs.data = (1000, [
        {"symbol": "FORMUSDT", "state": "forming", "score": 80},                        # bsa нет
        {"symbol": "OLDUSDT", "state": "ready", "score": 80, "bars_since_anchor": 100}])
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"FORMUSDT"}   # forming прошёл, старый нет


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


def test_findings_for_universe_maps_vendor_status_to_state(tmp_path):
    """Вендор-интеграция (урок vendor-integration-tests-not-mocks): build_scout кладёт стадию под
    ключом 'status' (viewmodel:542), НЕ 'state'. findings_for_universe обязан прочитать 'status' и
    отдать под контрактным 'state' — иначе стек Борса пуст навсегда, S8 немая. Мок эмитил 'state' и
    маскировал баг → тест против НАСТОЯЩЕЙ storage.db + build_scout, стек — провайдером."""
    from storage.db import DB

    from app.scout_reader import ScoutReader

    path = str(tmp_path / "scout.db")
    db = DB(db_path=path, owner=True)
    now = 1_000_000
    db.scout_control_mark(last_b_boundary_ms=now)       # ненулевой курсор скана
    db.scout_findings_put_snapshot(
        [{"symbol": "BTCUSDT", "status": "ready", "tf": "4h", "score": 90, "bars_since_anchor": 12},
         {"symbol": "ETHUSDT", "status": "tracking", "tf": "4h", "score": 70}],
        now, "4h",
    )
    reader = ScoutReader(scout_db_path=path, worker_reader=object(),
                         detector_version="test", producer="test")
    scan_ms, findings = reader.findings_for_universe()
    by = {f["symbol"]: f for f in findings}
    assert scan_ms == now
    assert by["BTCUSDT"]["state"] == "ready" and by["BTCUSDT"]["bars_since_anchor"] == 12
    assert by["ETHUSDT"]["state"] == "tracking"          # status→state смаппилось
    # сквозняк: провайдер РЕАЛЬНО наполнил стек этими символами (без фикса стек был бы пуст)
    dv = DynamicUniverse(types.SimpleNamespace(
        dynamic_coins_path=str(tmp_path / "coins.json"), dynamic_stack_max=3,
        dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0), reader)
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"BTCUSDT", "ETHUSDT"}
    reader.close()


def test_engine_state_stack_only_when_provided():
    """mapper.engine_state: stack ТОЛЬКО при динамике; без него ключа нет (Персиваль чист)."""
    from app import mapper
    assert "stack" not in mapper.engine_state({})
    st = mapper.engine_state({}, stack={"cap": 10, "count": 1, "items": [{"symbol": "BTCUSDT"}]})
    assert st["stack"]["count"] == 1 and st["stack"]["cap"] == 10
