"""execution — постановка ордеров (executor: динамич. reduce-only TP/SL) и событийная
машина выходов V8.1 (lifecycle: on_bar_close/on_fill). Веха 3.

Публичный контракт: Action + конструкторы + фабрика setup-карточки (execution.actions)
+ решатель on_bar_close/on_fill + leg_targets/retarget (execution.lifecycle)."""
from .actions import (  # noqa: F401
    Action, NONE, PLACE, REBUILD, UPDATE_TP_SL, CLOSE, SKIP_FILLED,
    PENDING, OPEN, CLOSED, LV,
    new_setup, setup_from_signal, new_leg, open_legs,
    none, place, rebuild, update_tp_sl, close, skip_filled,   # конструкторы Action
)
from .lifecycle import on_bar_close, on_fill, leg_targets, retarget  # noqa: F401
