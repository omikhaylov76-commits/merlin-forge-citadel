# -*- coding: utf-8 -*-
"""execution.actions — КОНТРАКТ событийной машины выходов V8.1 (Веха 3, фича lifecycle).

Здесь только ДАННЫЕ, без логики решений: тип Action (что надо сделать с биржей) и фабрика
in-memory setup-словаря (карточка ведомой сделки). Импортируют и lifecycle (решатель), и
executor (исполнитель, следующая фича), и parity-тест — чтобы у всех один контракт.

Геометрия цен — через движок (pf.fib_price): entries/stop карточки байт-в-байт == бэктест (parity).
"""
from dataclasses import dataclass, field

import config
from strategy.engine import pifagor_fib_backtest_v2_clean as pf

# Фибо-уровни ног — литерал движка (v8_sim.py:32). Анти-дрейф пинуется тестом против v8_sim.LV.
LV = [0.382, 0.5, 0.618]

# Фазы ноги.
PENDING = "pending"
OPEN = "open"
CLOSED = "closed"

# Виды Action.
NONE = "NONE"
PLACE = "PLACE"               # поставить 3 PostOnly-лимитки + вшитый SL fib1.0 + нач. TP
REBUILD = "REBUILD"           # пере-якорь до commit: отменить pending + переставить новую сетку
UPDATE_TP_SL = "UPDATE_TP_SL" # amend reduce-only TP/SL открытых ног (бегунок/БУ/нога3/shock/скальп)
CLOSE = "CLOSE"               # закрыть открытые ноги рынком; reason ∈ {timeout, complete, eod}
SKIP_FILLED = "SKIP_FILLED"   # пере-якорь запрошен, но нога уже залита -> заморозить якорь
REPRICE_ENTRY = "REPRICE_ENTRY"  # двойной заход: сдвинуть resting entry-лимитку ноги вверх на допуск (2b amend)

ACTION_KINDS = frozenset({NONE, PLACE, REBUILD, UPDATE_TP_SL, CLOSE, SKIP_FILLED, REPRICE_ENTRY})


@dataclass(frozen=True)
class Action:
    """Намерение машины выходов. Сама бирже ничего не шлёт — это делает executor.
    kind ∈ ACTION_KINDS; payload — форма зависит от kind (см. конструкторы ниже)."""
    kind: str
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"неизвестный Action.kind={self.kind!r}; допустимо {sorted(ACTION_KINDS)}")


# ── Конструкторы Action (централизуют форму payload) ─────────────────────────
def none():
    return Action(NONE)


def place(setup):
    """3 ноги (lv, entry) + общий стоп + сторона — для первичной постановки сетапа."""
    legs = [{"lv": lg["lv"], "entry": lg["entry"]} for lg in _legs_by_lv(setup)]
    return Action(PLACE, {"legs": legs, "stop": setup["stop0"], "side": setup["side"]})


def rebuild(setup):
    """Пере-якорь до commit: та же форма, что PLACE (новая сетка от пере-якоренного B)."""
    legs = [{"lv": lg["lv"], "entry": lg["entry"]} for lg in _legs_by_lv(setup)]
    return Action(REBUILD, {"legs": legs, "stop": setup["stop0"], "side": setup["side"]})


def update_tp_sl(updates):
    """updates: [{lv, target, stop}] — новые reduce-only TP/SL на открытые ноги."""
    return Action(UPDATE_TP_SL, {"updates": list(updates)})


def close(legs, reason):
    """Закрыть рынком ноги (список lv) с причиной timeout|complete|eod."""
    return Action(CLOSE, {"legs": list(legs), "reason": reason})


def skip_filled():
    return Action(SKIP_FILLED)


def reprice_entry(lv, price):
    """Двойной заход: пере-ставить resting entry-лимитку ноги lv на сдвинутую цену price
    (=entries[lv]+tol*|B-A|). payload {lv, price}; qty пере-считывает executor (сайзинг-шов, F-M2)."""
    return Action(REPRICE_ENTRY, {"lv": lv, "price": float(price)})


# ── In-memory модель сделки (карточка сетапа) ────────────────────────────────
def new_leg(lv, entry):
    """Нога сетапа. Ставятся при заливе/ведении (lifecycle):
    - istop — РЕКОРД-стоп: фиксируется = stop0 ПРИ заливе и НЕ меняется (как движок v8_sim.py:143/230,
      Trade.stop). Для записи/parity-сверки.
    - resting_stop — ЭФФЕКТИВНЫЙ стоящий SL на бирже (stop0 либо entry=БУ для бегунка). Двигается.
    - target — текущая стоящая reduce-only цель.
    order_id/link_id/filled/qty — live-only, populate executor/state (lifecycle — passthrough)."""
    return {
        "lv": lv, "state": PENDING, "entry": float(entry),
        "ebar": None, "istop": None, "target": None, "resting_stop": None,
        "order_id": None, "link_id": None, "filled": False, "qty": None,
    }


def new_setup(side, A, B, jc, *, stop_fib=None, bar_time=None):
    """Карточка ведомой сделки из геометрии (side, A, B, индекс пробоя jc).

    entries/stop0 считает ДВИЖОК (pf.fib_price) — байт-в-байт бэктест (parity). stop_fib по умолчанию
    из config.execution (1.0 -> stop == A). Флаги/счётчики — стартовые (до залива). Без логики решений.
    """
    if stop_fib is None:
        stop_fib = config.execution.STOP_FIB
    lp = lambda level: float(pf.fib_price(A, B, level, side))
    legs = {lv: new_leg(lv, lp(lv)) for lv in LV}
    return {
        "side": side, "A": float(A), "B": float(B), "jc": int(jc),
        "stop0": lp(stop_fib), "stop_fib": float(stop_fib),   # эффективный stop_fib в карточке = единый источник (пере-якорь читает его)
        "committed": False, "beyond_B": False, "profit_taken": False, "spring_recorded": False,
        "leg1_scalped": False,   # двойной заход: 0.382 сняла скальп 0.236 → взводит допуск 0.5; grid-локальный, сброс на пере-якоре
        "wait_precommit": 0, "wait_postcommit": 0,
        "legs": legs,
        "bar_time": (int(bar_time) if bar_time is not None else None),
        "gen": None,   # нонс постановки orderLinkId; проставляет executor.presize/place/rebuild при (пере)постановке
    }


def setup_from_signal(sig):
    """Удобная обёртка: карточка из dict find_signal (strategy.signal). Интеграция (фича 5).
    Прокидывает эффективный sig['stop_fib'] в карточку (нет в sig -> new_setup падёт на config-дефолт),
    чтобы stop0 сигнала и stop0 карточки/пере-якоря брали ОДНО значение (не статику)."""
    return new_setup(sig["side"], sig["A"], sig["B"], sig["jc"],
                     stop_fib=sig.get("stop_fib"), bar_time=sig.get("bar_time"))


def open_legs(setup):
    """lv открытых ног (state==open), по возрастанию уровня."""
    return [lv for lv in LV if setup["legs"][lv]["state"] == OPEN]


def _legs_by_lv(setup):
    return [setup["legs"][lv] for lv in LV]
