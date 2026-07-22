"""Тесты scout-маппера (ADR-0016 #52): находка скаута → контрактный снимок.

Главный гвоздь — вывод маппера ВАЛИДЕН против contracts/telemetry-scout.schema.json (адаптер
привязан к контракту). Плюс: levels/config_mismatch/orders/position/все-required (вкл. data_upto).
"""

import json
from pathlib import Path

import jsonschema

from app import mapper

_ITEM = json.loads(
    (Path(__file__).resolve().parents[3] / "contracts" / "telemetry-scout.schema.json").read_text()
)["items"]
_FMT = jsonschema.FormatChecker()

_READY = {
    "symbol": "BTCUSDT", "tf": "4h", "status": "ready", "score": 78, "bars_since_anchor": 3,
    "A": 68000.0, "B": 72000.0,
    "entries": {"0.382": 70472.0, "0.5": 70000.0, "0.618": 69528.0}, "stop": 68000.0,
}
_FORMING = {"symbol": "WIFUSDT", "tf": "4h", "status": "forming", "score": 41}
_EFF_CLEAN = {"SHORTS_ENABLED": False, "EMA_FILTER_ENABLED": False,
              "REANCHOR_AFTER_SCALP": True, "STOP_FIB": 1.0}


def _snap(finding, **over):
    kw = dict(
        worker_eff=_EFF_CLEAN, scout_stop_fib=1.0, orders_raw=None, position=None,
        detector_version="v81-b75bd17", producer="pifagor-scout",
        scan_ts_iso="2026-07-16T12:00:00+00:00", orders_ts_iso="2026-07-16T12:00:05+00:00",
        data_upto_iso="2026-07-16T12:00:00+00:00",
    )
    kw.update(over)
    return mapper.scout_snapshot(finding, **kw)


def test_ready_snapshot_schema_valid():
    s = _snap(_READY)
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert {lv["role"] for lv in s["levels"]} == {
        "A", "B", "entry_0382", "entry_05", "entry_0618", "stop"
    }
    assert s["bars_since_anchor"] == 3
    assert "klines" not in s and "klines_tf" not in s  # Фаза 1 — свечи опущены


def test_forming_snapshot_schema_valid_no_levels():
    s = _snap(_FORMING)
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert "levels" not in s          # forming — уровней ещё нет
    assert "bars_since_anchor" not in s


def test_all_required_present():
    s = _snap(_READY)
    for req in _ITEM["required"]:     # ВСЕ required схемы, включая data_upto
        assert req in s, f"нет required-поля {req}"


def test_config_mismatch_flag_and_details():
    s = _snap(_READY, worker_eff={**_EFF_CLEAN, "REANCHOR_AFTER_SCALP": False})
    assert s["config_mismatch"]["flag"] is True
    d = s["config_mismatch"]["details"]["REANCHOR_AFTER_SCALP"]
    assert d == {"scout": True, "worker": False}


def test_config_mismatch_clean():
    assert _snap(_READY)["config_mismatch"]["flag"] is False


def test_config_mismatch_empty_eff_no_blind_flag():
    # конфиг движка не прочитался (worker_eff пуст) → НЕ поднимаем flag вслепую (ложная плашка)
    assert _snap(_READY, worker_eff={})["config_mismatch"]["flag"] is False


def test_config_mismatch_stop_fib():
    # STOP_FIB воркера (0.5) ≠ допущение скаута (1.0) → mismatch
    s = _snap(_READY, worker_eff={**_EFF_CLEAN, "STOP_FIB": 0.5}, scout_stop_fib=1.0)
    assert s["config_mismatch"]["flag"] is True
    assert "STOP_FIB" in s["config_mismatch"]["details"]


def test_orders_and_position_mapping():
    orders = [{"order_id": "o1", "entry": 70472.0, "qty": 0.01, "filled": False, "side": "buy",
               "level": 0.382, "tgt": 71000.0}]
    pos = {"symbol": "BTCUSDT", "side": "long", "size": 0.5, "avgPrice": 70000.0,
           "unrealisedPnl": -12.5}
    s = _snap(_READY, orders_raw=orders, position=pos)
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert s["orders"][0] == {
        "order_id": "o1", "side": "buy", "type": "limit", "px": 70472.0,
        "qty": 0.01, "status": "pending",
    }
    assert s["position"] == {"side": "long", "avg_px": 70000.0, "size": 0.5, "live_pnl": -12.5}


def test_dry_run_no_orders_no_position():
    s = _snap(_READY)  # dry-run: ордеров/позиции нет
    assert "orders" not in s and "position" not in s


def test_snapshot_with_candles():
    # хвост #52: свечи скан-ТФ из кэша → klines + klines_tf=tf сетапа; проходит схему
    candles = [{"time": 1720699200000, "open": 71000.0, "high": 71500.0, "low": 70800.0,
                "close": 71200.0, "volume": 123.4}]
    s = _snap(_READY, candles=candles, klines_tf="4h")
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert s["klines_tf"] == "4h"
    assert s["klines"][0] == {"time": 1720699200000, "o": 71000.0, "h": 71500.0, "l": 70800.0,
                              "c": 71200.0, "v": 123.4}


def test_snapshot_no_candles_omits_klines():
    s = _snap(_READY)  # candles=None → klines/klines_tf опущены (валидно)
    assert "klines" not in s and "klines_tf" not in s


# ── engine_truth (S8 единая Разведка): дескриптор warm.classify → факты Контракта ──────────

_DESC = {
    "kind": "PENDING", "auto_eligible": True, "reanchored": False, "side": "long",
    "age_bars": 2, "entries": {0.382: 103.423, 0.5: 102.75, 0.618: 102.077},
    "stop": 99.9, "targets": {0.382: 108.0}, "est_risk_pct": 3.4,
}


def test_engine_truth_maps_descriptor_facts():
    e = mapper.engine_truth(_DESC, in_universe=True)
    assert e["kind"] == "PENDING" and e["auto_eligible"] is True and e["reanchored"] is False
    assert e["in_universe"] is True and e["side"] == "long" and e["age_bars"] == 2
    assert e["entries"]["0.382"] == 103.423 and e["stop"] == 99.9   # ключи-строки (JSON)
    assert e["targets"]["0.382"] == 108.0 and e["est_risk_pct"] == 3.4


def test_engine_truth_none_descriptor_is_honest_verdict():
    """None-дескриптор = «активного сетапа нет» — поле ЕСТЬ, kind=null (не «неизвестно»)."""
    e = mapper.engine_truth(None, in_universe=False)
    assert e == {"kind": None, "auto_eligible": False, "reanchored": False, "in_universe": False}


def test_engine_truth_drops_invalid_prices():
    d = {**_DESC, "entries": {0.382: 0.0, 0.5: -1.0}, "stop": 0.0, "targets": {}}
    e = mapper.engine_truth(d, in_universe=True)
    assert "entries" not in e and "stop" not in e and "targets" not in e


def test_snapshot_with_engine_schema_valid():
    s = _snap(_READY, engine=mapper.engine_truth(_DESC, in_universe=True))
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert s["engine"]["kind"] == "PENDING"


def test_snapshot_with_null_verdict_engine_schema_valid():
    s = _snap(_READY, engine=mapper.engine_truth(None, in_universe=True))
    jsonschema.validate(s, _ITEM, format_checker=_FMT)
    assert s["engine"]["kind"] is None


def test_snapshot_without_engine_unchanged():
    assert "engine" not in _snap(_READY)          # аддитивность: прежние потребители чисты
