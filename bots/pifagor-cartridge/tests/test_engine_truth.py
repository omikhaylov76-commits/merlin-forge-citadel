"""Единая Разведка (S8): поле `engine` (правда движка per-coin) против НАСТОЯЩЕГО вендора.

Урок S7 (vendor-integration-tests-not-mocks): вердикты берём из живого `warm.classify` на
синтетических 4h-сериях в настоящей scout.db (series откалиброваны зондом по detect_v81):
PENDING auto_eligible / PENDING reanchored (кнопка) / OPEN (вход ушёл) / None (реплей закрыл).
Плюс границы: короткая серия → снимок БЕЗ engine («неизвестно» ≠ «не берёт»), membership
in_universe (стек динамики / статичная вселенная фикс-бота), не-4h находка — без правды.
"""
import json

from storage.db import DB

from app.scout_reader import ScoutReader

NOW = 1_700_000_000_000
H4 = 4 * 3600 * 1000
SYM = "TSTUSDT"


class _WorkerDB:
    def orders_open_all(self):
        return []

    def account_get(self):
        return {"positions": json.dumps([])}


class _Worker:
    db = _WorkerDB()

    class config_store:  # noqa: N801 — мини-двойник атрибута
        @staticmethod
        def effective():
            return {}


def _seed_coin():
    """Пред-засев COINS_CONFIG мягкими порогами (mb 1.0) ДО реплея: setdefault _classify его
    не перебьёт, а дефолт динамики (mb1=2.0) синтетический пробой не прошёл бы."""
    import config as vcfg
    vcfg.strategy.COINS_CONFIG[SYM] = {
        "enabled": True, "mb1": 1.0, "mb2": 1.0, "leverage": 5, "weight": 1.0,
    }


def _reader(tmp_path) -> tuple[ScoutReader, DB]:
    _seed_coin()
    path = str(tmp_path / "scout.db")
    db = DB(db_path=path, owner=True, database_url="")
    db.scout_control_mark(last_b_boundary_ms=NOW)
    r = ScoutReader(scout_db_path=path, worker_reader=_Worker(),
                    detector_version="test", producer="test")
    return r, db


def _rows(quads):
    return [{"time": NOW + i * H4, "open": o, "high": h, "low": low, "close": c, "volume": 1.0}
            for i, (o, h, low, c) in enumerate(quads)]


def _flat(n, px=100.0):
    return [(px, px + 0.5, px - 0.5, px) for _ in range(n)]


# Синтетика, откалиброванная по НАСТОЯЩЕМУ detect_v81/warm.classify (зонд probe_warm_series):
_IMPULSE = [(100.0, 103.0, 99.9, 102.9)]                    # толчок-1: 3% чистый
_CONSOL = [(102.9, 103.0, 102.2, 102.5)]                    # консолидация без отмены
_BREAKOUT = [(102.5, 105.6, 102.4, 105.4)]                  # пробой h[толчка]=103
_HOVER = [(105.4, 105.5, 104.6, 105.0), (105.0, 105.5, 104.6, 105.2)]   # виснем над входами
_NEWHIGH = [(105.4, 108.9, 105.2, 108.5), (108.5, 108.9, 107.6, 108.0)]  # REBUILD → пере-якорь
_DIP = [(104.0, 104.2, 103.0, 103.6), (103.6, 104.0, 103.4, 103.8)]     # залив 0.382 без цели
_CRASH = [(105.4, 105.5, 99.0, 99.5), (99.5, 100.0, 99.0, 99.8)]        # до стопа → закрыт

AUTO = _flat(60) + _IMPULSE + _CONSOL + _BREAKOUT + _HOVER
REANCHORED = _flat(60) + _IMPULSE + _CONSOL + _BREAKOUT + _NEWHIGH
OPEN_GONE = _flat(60) + _IMPULSE + _CONSOL + _BREAKOUT + _DIP
CLOSED = _flat(60) + _IMPULSE + _CONSOL + _BREAKOUT + _CRASH


def _snap_with(tmp_path, quads, *, universe=frozenset({SYM}), tf="4h"):
    r, db = _reader(tmp_path)
    db.scout_klines_put_many(SYM, "4h", _rows(quads))
    db.scout_findings_put_snapshot(
        [{"symbol": SYM, "status": "tracking", "tf": tf, "score": 70,
          "A": 100.0, "B": 105.6, "entries": {"0.382": 103.4, "0.5": 102.8, "0.618": 102.1},
          "stop": 99.9}],
        NOW, tf)
    _, snaps = r.build_snapshots(universe=universe)
    r.close()
    (s,) = snaps
    return s


def test_auto_pending_engine_facts(tmp_path):
    """Нетронутый PENDING → самоход поставит: kind/auto/rean + сетка движка в фактах."""
    e = _snap_with(tmp_path, AUTO)["engine"]
    assert e["kind"] == "PENDING" and e["auto_eligible"] is True and e["reanchored"] is False
    assert e["in_universe"] is True and e["side"] == "long"
    assert abs(e["entries"]["0.382"] - 103.423) < 0.01 and abs(e["stop"] - 99.9) < 1e-9
    assert e["targets"]                                    # начальные цели постановки есть


def test_reanchored_pending_is_button_case(tmp_path):
    """Пере-якорь (REBUILD после пробоя) → auto снят, только кнопка (warm_apply, ADR-0022)."""
    e = _snap_with(tmp_path, REANCHORED)["engine"]
    assert e["kind"] == "PENDING" and e["auto_eligible"] is False and e["reanchored"] is True


def test_open_gone_market_entry(tmp_path):
    """Нога залита реплеем (вход по рынку ушёл) → OPEN, никогда не авто."""
    e = _snap_with(tmp_path, OPEN_GONE)["engine"]
    assert e["kind"] == "OPEN" and e["auto_eligible"] is False


def test_closed_replay_honest_none_verdict(tmp_path):
    """Реплей закрыл сделку (стоп) → ЧЕСТНЫЙ вердикт kind=null («проверено, не берёт»)."""
    e = _snap_with(tmp_path, CLOSED)["engine"]
    assert e["kind"] is None and e["auto_eligible"] is False and e["reanchored"] is False


def test_short_series_no_engine_key(tmp_path):
    """<60 баров → реплей недостоверен → снимка БЕЗ engine («неизвестно» ≠ «не берёт»)."""
    s = _snap_with(tmp_path, _flat(10))
    assert "engine" not in s


def test_out_of_universe_flag(tmp_path):
    """Годный сетап ВНЕ рабочего набора движка → in_universe=false (F-lookahead «мимо списка»)."""
    e = _snap_with(tmp_path, AUTO, universe=frozenset({"OTHERUSDT"}))["engine"]
    assert e["auto_eligible"] is True and e["in_universe"] is False


def test_static_universe_fallback_for_fixed_bot(tmp_path):
    """universe=None (фикс-бот без провайдера) → членство по enabled COINS_CONFIG на буте."""
    e = _snap_with(tmp_path, AUTO, universe=None)["engine"]
    assert e["in_universe"] is True                        # SYM засеян enabled ДО init читалки


def test_non_4h_finding_without_engine(tmp_path):
    """Правда движка — только торговый ТФ (SIGNAL_TF=4h); 1h-находка идёт без engine."""
    s = _snap_with(tmp_path, AUTO, tf="1h")
    assert "engine" not in s


def test_snapshots_validate_against_contract_schema(tmp_path):
    """Снимок С engine валиден против telemetry-scout.schema.json (schema-first гвоздь)."""
    from pathlib import Path

    import jsonschema
    item = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts" / "telemetry-scout.schema.json")
        .read_text())["items"]
    for i, quads in enumerate((AUTO, REANCHORED, OPEN_GONE, CLOSED)):
        sub = tmp_path / f"v{i}"
        sub.mkdir()
        s = _snap_with(sub, quads)
        jsonschema.validate(s, item, format_checker=jsonschema.FormatChecker())
