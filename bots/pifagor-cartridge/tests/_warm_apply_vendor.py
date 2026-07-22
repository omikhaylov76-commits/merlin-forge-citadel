"""Прогон в контексте ВЕНДОРА (app == vendor): F-warm-button (ADR-0022) против движка.

Кнопка «Поставить» = durable-интент WARM_APPLY → `maybe_warm` → `_warm_one_button`. Проверяем
условия подписи Куратора против НАСТОЯЩИХ вендор-функций: ставит ВАЛИДНЫЙ PENDING (вкл. reanchored
— в отличие от auto-пути `_warm_one`); OPEN→skip; has_active→skip; cap держит; single-shot (ack
гасит интент). Плюс контракт: `_parse_warm_approved(CSV)` == список (CSV пишет reader.warm_apply).
НЕ pytest (префикс `_`); exit!=0 при любом провале."""
import sys
from types import SimpleNamespace
from unittest import mock

from strategy import warm

from app import cycle

FAILS = []
log = mock.Mock()
EFF = {"CONCURRENCY_CAP": 10}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def _button(state, s):
    return cycle._warm_one_button(None, state, None, EFF, s, {}, logger=log)


# контракт интента: CSV (как пишет reader.warm_apply) и JSON-массив → список; пусто → []
check(cycle._parse_warm_approved("1INCHUSDT,EPICUSDT") == ["1INCHUSDT", "EPICUSDT"], "CSV")
check(cycle._parse_warm_approved('["BTCUSDT","ETHUSDT"]') == ["BTCUSDT", "ETHUSDT"], "JSON")
check(cycle._parse_warm_approved("") == [], "пусто не []")

# _warm_one_button: has_active → 0 (открытую позицию не трогает, урок 18.07)
check(_button(SimpleNamespace(has_active=lambda s: True), "BTCUSDT") == 0, "has_active не skip")

# КЛЮЧЕВОЕ: _warm_one_button СТАВИТ пере-якоренный PENDING — суть кнопки (auto-путь _warm_one его
# пропускает). Настоящая функция + патч fetch/cap/place.
_free = SimpleNamespace(has_active=lambda s: False)
cycle._warm_fetch_classify = lambda broker, eff, s, *, logger: (
    {"kind": warm.PENDING, "auto_eligible": False, "reanchored": True}, None)
cycle._warm_cap_ok = lambda state, eff: True
placed = []
cycle._warm_place = lambda state, ex, s, desc, t4, cur, *, logger: placed.append(s) or 1
check(_button(_free, "1INCHUSDT") == 1, "reanchored PENDING не поставлен (суть кнопки)")
check(placed == ["1INCHUSDT"], "_warm_place не позван на reanchored")

# OPEN → skip (вход по рынку в бэклоге)
cycle._warm_fetch_classify = lambda broker, eff, s, *, logger: ({"kind": "OPEN"}, None)
check(_button(_free, "BTCUSDT") == 0, "OPEN не skip")

# cap держит → skip
cycle._warm_fetch_classify = lambda broker, eff, s, *, logger: (
    {"kind": warm.PENDING, "reanchored": True}, None)
cycle._warm_cap_ok = lambda state, eff: False
check(_button(_free, "BTCUSDT") == 0, "cap не уважён")

# single-shot: maybe_warm ставит и гасит интент по ack (2-й вызов того же id → no-op)
cycle._warm_gate = lambda eff, state, ledger, broker: None
cycle._configure_executor = lambda *a, **k: None
cycle._log_event = lambda *a, **k: None
cycle._warm_cap_ok = lambda state, eff: True
cycle._warm_fetch_classify = lambda broker, eff, s, *, logger: (
    {"kind": warm.PENDING, "reanchored": True}, None)
runs = []
cycle._warm_place = lambda state, ex, s, desc, t4, cur, *, logger: runs.append(s) or 1
box = {"id": 7}
ack = {"v": None}
_store = SimpleNamespace(get_warm_ack=lambda: ack["v"],
                         set_warm_ack=lambda i: ack.__setitem__("v", i))
_ledger = SimpleNamespace(store=_store)
_db = SimpleNamespace(config_log_latest=lambda p: {"id": box["id"], "new": "1INCHUSDT"})
_state = SimpleNamespace(db=_db, has_active=lambda s: False)
_cfg = SimpleNamespace(effective=lambda strict=False: EFF)


def _mw():
    cycle.maybe_warm(None, _state, _cfg, _ledger, None, None, ["1INCHUSDT"], {}, logger=log)


_mw()
check(runs == ["1INCHUSDT"] and ack["v"] == 7, "1-й интент не сработал (ack≠7)")
_mw()
check(runs == ["1INCHUSDT"], "повторил тот же интент (не single-shot)")
box["id"] = 8
_mw()
check(runs == ["1INCHUSDT", "1INCHUSDT"] and ack["v"] == 8, "новый интент не сработал")

if FAILS:
    print("ADR-0022 F-warm-button vendor-прогон — ПРОВАЛЫ:")
    for _m in FAILS:
        print("  -", _m)
    sys.exit(1)
print("ADR-0022 F-warm-button vendor-прогон: все проверки зелёные")
sys.exit(0)
