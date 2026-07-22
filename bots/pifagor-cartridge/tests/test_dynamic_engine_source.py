"""F-lookahead v3 (подпись Куратора): вселенная ОТ ДВИЖКА — placeable-отбор по warm.classify из
scout_list, вместо скаут-курации. Против НАСТОЯЩЕГО вендора (урок vendor-integration-tests):
реальная storage.db (scout_list + scout_klines) + живой `warm.classify` на синт-сериях (калиброваны
зондом по detect_v81 (те же, что test_engine_truth). Плюс регресс-гвоздь: DYNAMIC_SOURCE=scout
(дефолт) == прежний путь байт-в-байт.
"""
import types

from storage.db import DB

from app.dynamic_universe import DynamicUniverse
from app.scout_reader import ScoutReader
from tests.test_engine_truth import H4, NOW, _rows

# Серии откалиброваны зондом под _DEFAULT_COIN (mb1=2.0/mb2=3.5) — ИМЕННО те пороги, что провайдер
# пишет в coins.json (движок REPLACE). placeable_scan ФОРСИТ _DEFAULT_COIN → seed не нужен.
_IMP = [(100.0, 105.0, 99.8, 104.8)]                       # импульс-1: 5% чистый (>mb1 2%)
_CONS = [(104.8, 105.0, 103.5, 104.0)]                     # консолидация без отмены
_BRK = [(104.0, 109.6, 103.9, 109.4)]                      # пробой 5.5% (>mb2 3.5%)
_HOVER = [(109.4, 109.6, 108.0, 108.8), (108.8, 109.5, 108.0, 109.0)]    # висим над входами
_NEWHI = [(109.4, 114.0, 109.2, 113.6), (113.6, 114.0, 112.5, 113.0)]    # REBUILD → пере-якорь
_DIP = [(108.0, 108.3, 105.0, 105.5), (105.5, 106.0, 105.0, 105.8)]      # залив входа 0.382
_CRASH = [(109.4, 109.6, 99.0, 99.5), (99.5, 100.0, 99.0, 99.8)]         # до стопа → закрыт


def _flat(n):
    return [(100.0, 100.3, 99.7, 100.0) for _ in range(n)]


_AUTO = _flat(60) + _IMP + _CONS + _BRK + _HOVER           # PENDING auto_eligible → самоход ставит
_REAN = _flat(60) + _IMP + _CONS + _BRK + _NEWHI           # PENDING reanchored → «нужна кнопка»
_OPEN = _flat(60) + _IMP + _CONS + _BRK + _DIP             # OPEN (нога залита) → не placeable
_DEAD = _flat(60) + _IMP + _CONS + _BRK + _CRASH           # None (реплей закрыл) → не placeable

# монеты пула (scout_list) с сериями и скором КАЧЕСТВА
POOL = {
    "AUTOUSDT": (_AUTO, 90),
    "AUTO2USDT": (_AUTO, 60),        # ещё один auto (приоритет/сорт по скору качества)
    "BTNUSDT": (_REAN, 88),          # reanchored → после auto
    "OPENUSDT": (_OPEN, 95),         # OPEN → НЕ placeable, топ-скор не спасает
    "DEADUSDT": (_DEAD, 99),         # None → НЕ placeable, топ-скор не спасает
}


def _reader(tmp_path):
    path = str(tmp_path / "scout.db")
    db = DB(db_path=path, owner=True, database_url="")
    db.scout_control_mark(last_b_boundary_ms=NOW)             # ненулевой курсор скана
    # курированный ПУЛ (scout_list) + свежие свечи каждой монеты (Этап B их докачивает в проде)
    db.scout_list_put_snapshot(
        [{"symbol": s, "score": sc, "mb1": 1.0, "mb2": 1.0, "bar_source": "config"}
         for s, (_, sc) in POOL.items()], NOW)
    for s, (quads, _) in POOL.items():
        db.scout_klines_put_many(s, "4h", _rows(quads))
    r = ScoutReader(scout_db_path=path, worker_reader=object(),
                    detector_version="test", producer="test")
    return r, db


def _provider(tmp_path, reader, **crit):
    cfg = types.SimpleNamespace(
        dynamic_source="engine", dynamic_coins_path=str(tmp_path / "coins.json"),
        dynamic_stack_max=crit.get("stack_max", 10), dynamic_enter_scans=1, dynamic_exit_scans=2,
        dynamic_min_write_s=0.0, dynamic_criteria_path="",
        dynamic_min_score=crit.get("min_score", 0), dynamic_fresh_bars=0)
    return DynamicUniverse(cfg, reader)


# ── Слой 1: placeable_scan против живого вендора ──────────────────────────────

def test_placeable_scan_picks_only_pending(tmp_path):
    """warm.classify по пулу: PENDING (auto|reanchored) → placeable; OPEN/None → мимо."""
    r, _ = _reader(tmp_path)
    scan_ms, placeable = r.placeable_scan()
    assert scan_ms == NOW
    assert set(placeable) == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}   # OPEN/DEAD отсеяны
    assert placeable["AUTOUSDT"]["auto_eligible"] and not placeable["AUTOUSDT"]["reanchored"]
    assert placeable["BTNUSDT"]["reanchored"] and not placeable["BTNUSDT"]["auto_eligible"]
    assert "OPENUSDT" not in placeable    # OPEN (в позиции) — не свежая постановка
    assert "DEADUSDT" not in placeable    # None (реплей закрыл) — не placeable
    r.close()


def test_placeable_scan_forces_default_mb_over_static(tmp_path):
    """АДВЕРС-ФИКС: монета с ЧУЖИМ mb в COINS_CONFIG (как статик-вендор AAVE 2.5/4.0) всё равно
    классифицируется _DEFAULT_COIN (2.0/3.5) — вердикт адаптера == постановка движка (coins.json
    REPLACE, не унаследованный mb). Иначе universe разошёлся бы с реальной постановкой."""
    import config as vcfg
    r, _ = _reader(tmp_path)
    # пред-ставим AUTOUSDT ЖЁСТКИЙ mb, при котором его 5.5%-пробой НЕ прошёл бы (mb2=9)
    vcfg.strategy.COINS_CONFIG["AUTOUSDT"] = {"enabled": True, "mb1": 8.0, "mb2": 9.0,
                                              "leverage": 5, "weight": 1.0}
    _, placeable = r.placeable_scan()
    assert "AUTOUSDT" in placeable                                   # форс перебил жёсткий mb
    assert vcfg.strategy.COINS_CONFIG["AUTOUSDT"]["mb2"] == 3.5      # _DEFAULT_COIN применён
    r.close()


def test_default_source_scout_uses_findings_not_placeable(tmp_path):
    """РЕГРЕСС-ГВОЗДЬ (условие подписи): дефолт (без dynamic_source) = scout-путь — провайдер зовёт
    findings_for_universe, НЕ placeable_scan. Флот и Борс-в-scout-режиме байт-в-байт."""
    calls = {"findings": 0, "placeable": 0}

    class _Spy:
        def findings_for_universe(self):
            calls["findings"] += 1
            return (0, [])

        def placeable_scan(self):
            calls["placeable"] += 1
            return (0, {})

    cfg = types.SimpleNamespace(       # БЕЗ dynamic_source — как старые конструкторы
        dynamic_coins_path=str(tmp_path / "coins.json"), dynamic_stack_max=3,
        dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0)
    dv = DynamicUniverse(cfg, _Spy())
    assert dv._source == "scout"       # дефолт
    dv.tick(1.0)
    assert calls == {"findings": 1, "placeable": 0}   # scout-путь: только findings


def test_engine_gates_expensive_scan_on_cursor(tmp_path):
    """EFFICIENCY: engine-режим гейтит ДЕШЁВЫМ last_scan_ms ДО дорогого placeable_scan.
    Тот же scan_ms второй раз → placeable_scan НЕ гоняется (не жжём CPU/лог каждый тик)."""
    calls = {"cursor": 0, "placeable": 0}

    class _Spy:
        def last_scan_ms(self):
            calls["cursor"] += 1
            return 500

        def placeable_scan(self):
            calls["placeable"] += 1
            return (500, {})

    cfg = types.SimpleNamespace(
        dynamic_source="engine", dynamic_coins_path=str(tmp_path / "coins.json"),
        dynamic_stack_max=3, dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0)
    dv = DynamicUniverse(cfg, _Spy())
    dv.tick(1.0)                                # новый scan_ms=500 → дорогой скан 1 раз
    dv.tick(2.0)                                # тот же 500 → гейт по курсору, placeable НЕ зовём
    assert calls == {"cursor": 2, "placeable": 1}


def test_scan_list_rows_reads_quality_pool(tmp_path):
    """scan_list_rows читает курированный scout_list вендора (symbol+score), не сырую вселенную."""
    r, _ = _reader(tmp_path)
    rows = {x["symbol"]: x["score"] for x in r.scan_list_rows()}
    assert rows == {"AUTOUSDT": 90, "AUTO2USDT": 60, "BTNUSDT": 88, "OPENUSDT": 95, "DEADUSDT": 99}
    r.close()


# ── Слой 2: провайдер в engine-режиме ────────────────────────────────────────

def test_engine_source_stack_is_placeable_only(tmp_path):
    """Стек engine-режима = ТОЛЬКО placeable (3), НЕ топ-скор OPEN/None (misalignment снят)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}
    r.close()


def test_engine_source_auto_prioritised_over_reanchored(tmp_path):
    """Кап < числа placeable: auto-годные ПЕРВЫМИ (самоход возьмёт), reanchored — после."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r, stack_max=2)     # кап 2 из 3 placeable
    dv.tick(2.0)
    got = {i["symbol"] for i in dv.view()["items"]}
    assert got == {"AUTOUSDT", "AUTO2USDT"}       # два auto вошли, reanchored BTN не влез (кап)
    assert "BTNUSDT" not in got
    r.close()


def test_engine_source_writes_coins_json(tmp_path):
    """Стек пишется в coins.json дефолт-блоком (разъём движка COINS_CONFIG_PATH)."""
    import json
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    coins = json.load(open(tmp_path / "coins.json"))
    assert set(coins) == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}
    assert coins["AUTOUSDT"] == {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                 "leverage": 5, "weight": 1.0}
    r.close()


def test_engine_source_min_score_quality_filter(tmp_path):
    """min_score канала в engine-режиме → доп-порог к скору КАЧЕСТВА scan_list (условие подписи)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r, min_score=70)     # AUTO2 (60) отсекается по качеству
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AUTOUSDT", "BTNUSDT"}
    r.close()


def test_engine_source_pin_holds_open_position(tmp_path):
    """Предохранитель Вехи 2: held (открытая позиция) ЗАПИНЕН даже если не placeable (OPEN/None) —
    при переключении источника позиция не осиротеет (линза Куратора)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0, frozenset({"DEADUSDT"}))         # позиция на DEAD (None-вердикт), но held
    v = {i["symbol"]: i for i in dv.view()["items"]}
    assert "DEADUSDT" in v and v["DEADUSDT"]["pinned"] is True   # пин держит, не placeable не важно
    r.close()


def test_engine_source_empty_pool_keeps_stack(tmp_path):
    """Пул пуст (scout_list не прочёлся) → placeable пуст → ПОЛ-НА-ПУСТОТУ держит набор."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    assert dv.view()["count"] == 3
    r.scout_db.scout_list_put_snapshot([], NOW + H4)          # пул опустел
    r.scout_db.scout_control_mark(last_b_boundary_ms=NOW + H4)  # новый скан
    dv.tick(3.0)
    # placeable пуст → кандидатов нет; существующие уходят по exit-гистерезису, НЕ разом
    assert dv.view()["count"] == 3                            # missed=1 < exit=2 → держим
    r.close()
