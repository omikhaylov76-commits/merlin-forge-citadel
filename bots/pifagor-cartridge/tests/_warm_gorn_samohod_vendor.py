"""Прогон в контексте ВЕНДОРА (app == vendor): проверки ADR-0021 (горн + самоход) против движка.

Регулярный пакет `app` есть и у картриджа, и у вендора → вендорный app.cycle/app.main из общего
набора картриджа не импортируется. Изолированный процесс (cwd=vendor) = контекст движка в проде.
НЕ pytest-тест (префикс `_`) — не собирается. exit!=0 при любом провале."""
import sys
from types import SimpleNamespace
from unittest import mock

import config
from market.klines_4h import FOUR_HOUR_MS

from app import cycle
from app import main as vmain

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


# условие подписи #1: тождество 4h (страж флота) + прочие ТФ + fail-loud
check(vmain._signal_tf_ms("4h") == FOUR_HOUR_MS == 14_400_000, "4h != FOUR_HOUR_MS")
check(vmain._signal_tf_ms("1h") == 3_600_000, "1h")
check(vmain._signal_tf_ms("15m") == 900_000, "15m")
check(vmain._signal_tf_ms("1d") == 86_400_000, "1d")
# LOW-1 (ревью): реальный SIGNAL_TF, не литерал — опечатка «4hr» → красный CI, не краш-луп
check(vmain._signal_tf_ms(config.strategy.SIGNAL_TF) == FOUR_HOUR_MS, "SIGNAL_TF != 4h")
for bad in ("", "4x", "abc", "0h", "-1h"):
    try:
        vmain._signal_tf_ms(bad)
        check(False, f"_signal_tf_ms({bad!r}) должен свалиться")
    except ValueError:
        pass

# условие #1 (часть 2): границы _maybe_4h_cycle при 4h идентичны дореформенным (FOUR_HOUR_MS)
step = vmain._signal_tf_ms("4h")
check(all((now // step) * step == (now // FOUR_HOUR_MS) * FOUR_HOUR_MS
          for now in range(0, 5 * FOUR_HOUR_MS, 900_000)), "границы разошлись")

# cycle._warm_one: has_active → 0 (позицию не трогает, урок 18.07) — ДО monkeypatch
_active = SimpleNamespace(has_active=lambda s: True)
check(cycle._warm_one(None, _active, None, {}, "BTCUSDT", {}, logger=mock.Mock()) == 0,
      "_warm_one не пропустил has_active")

# настоящий cycle._warm_one: пере-якоренный (auto_eligible=False) → 0 (не протекает F-warm-button)
cycle._warm_fetch_classify = lambda broker, eff, s, *, logger: ({"auto_eligible": False}, None)
_free = SimpleNamespace(has_active=lambda s: False)
check(cycle._warm_one(None, _free, None, {}, "BTCUSDT", {}, logger=mock.Mock()) == 0,
      "_warm_one поставил пере-якоренный")

# routing: warm_auto_now → _warm_one (auto_eligible), не _warm_one_button (последним)
seen = {"one": [], "button": []}
cycle._warm_gate = lambda eff, state, ledger, broker: None
cycle._configure_executor = lambda *a, **k: None
cycle._warm_one = lambda b, st, ex, eff, s, cur, *, logger: seen["one"].append(s) or 1
cycle._warm_one_button = lambda *a, **k: seen["button"].append("!") or 1
cfg = SimpleNamespace(effective=lambda strict=False: {"CONCURRENCY_CAP": 10})
n = cycle.warm_auto_now(None, None, cfg, None, None, None, ["BTCUSDT", "ETHUSDT"], {},
                        logger=mock.Mock(), label="самоход")
check(seen["one"] == ["BTCUSDT", "ETHUSDT"], "warm_auto_now не через _warm_one")
check(seen["button"] == [], "warm_auto_now пошёл через _warm_one_button (пере-якорь)")
check(n == 2, "warm_auto_now вернул не 2")

# условие подписи #2: гейт-флаг fail-closed (spy разрешён Куратором для «не вызван»)
calls = []
vmain.warm_auto_now = lambda *a, **k: calls.append(k.get("label"))
vmain.run_4h_cycle = lambda *a, **k: None


def _fake_cycle(flag):
    return SimpleNamespace(_last_4h_boundary=0, _warm_each_cycle=flag, broker=None, state=None,
                           cfg=None, ledger=None, executor=None, working_provider=None, symbols=[],
                           cursors={}, log=mock.Mock(), _write_warm_candidates=lambda: None,
                           _write_scan_snapshot=lambda now_ms: None)


vmain.PifagorApp._maybe_4h_cycle(_fake_cycle(False), FOUR_HOUR_MS)
check(calls == [], "флаг OFF: warm_auto_now вызван (не fail-closed)")
vmain.PifagorApp._maybe_4h_cycle(_fake_cycle(True), FOUR_HOUR_MS)
check(calls == ["самоход"], "флаг ON: самоход не вызван")

# горн: single-shot по in-memory курсору (init=latest на старте)
calls2 = []
vmain.warm_auto_now = lambda *a, **k: calls2.append(k.get("label"))
box = {"id": 5}
_db = SimpleNamespace(config_log_latest=lambda p: {"id": box["id"]})
_app = SimpleNamespace(state=SimpleNamespace(db=_db), _warm_auto_now_ack=0, broker=None,
                       cfg=None, ledger=None, executor=None, working_provider=None, symbols=[],
                       cursors={}, log=mock.Mock())
vmain.PifagorApp._maybe_warm_auto_now(_app)
check(calls2 == ["горн"] and _app._warm_auto_now_ack == 5, "горн: 1-й интент не сработал")
vmain.PifagorApp._maybe_warm_auto_now(_app)
check(calls2 == ["горн"], "горн: повторил тот же интент (не single-shot)")
box["id"] = 6
vmain.PifagorApp._maybe_warm_auto_now(_app)
check(calls2 == ["горн", "горн"] and _app._warm_auto_now_ack == 6, "горн: новый интент не сработал")


# горн: ack двигается ДАЖЕ при сбое warm_auto_now (single-shot при исключении — не долбит)
def _boom(*a, **k):
    raise RuntimeError("boom")


vmain.warm_auto_now = _boom
box2 = {"id": 9}
_db2 = SimpleNamespace(config_log_latest=lambda p: {"id": box2["id"]})
_app2 = SimpleNamespace(state=SimpleNamespace(db=_db2), _warm_auto_now_ack=0, broker=None, cfg=None,
                        ledger=None, executor=None, working_provider=None, symbols=[], cursors={},
                        log=mock.Mock())
vmain.PifagorApp._maybe_warm_auto_now(_app2)
check(_app2._warm_auto_now_ack == 9, "горн: ack не сдвинут при сбое → долбит")

if FAILS:
    print("ADR-0021 vendor-прогон — ПРОВАЛЫ:")
    for _m in FAILS:
        print("  -", _m)
    sys.exit(1)
print("ADR-0021 vendor-прогон: все проверки зелёные")
sys.exit(0)
