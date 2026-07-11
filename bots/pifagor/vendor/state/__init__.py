"""state — атомарное хранилище сетапов (StateStore) поверх storage + reconcile фаз с биржей
(ADR 0008, «биржа=арбитр», one-way) — Веха 3. Схема setup_state (per-leg фазы).
CapitalStore (снимок леджера capital_state, id=1) — Веха 4 фича 1 (ADR 0010).
ConfigStore (рантайм-крутилки config_state + журнал config_log) — Веха 4 фича 2 (docs/14 §3)."""
from .store import StateStore
from .capital import CapitalStore
from .config import ConfigStore
from .reconcile import reconcile_setup, reconcile_on_start

__all__ = ["StateStore", "CapitalStore", "ConfigStore", "reconcile_setup", "reconcile_on_start"]
