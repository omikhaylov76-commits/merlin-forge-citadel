"""risk_capital — sizing (размер ноги от working) + concurrency (cap=8 по залитым) — Веха 3.
ledger (working/cushion), refinance (50/50 мес), killswitch (−50/−40) — Веха 4 фича 1 (ADR 0010)."""
from .sizing import position_fraction, leg_qty, make_sizing_callback
from .concurrency import count_open_legs, slots_free, can_place_leg, admissible_legs
from .ledger import Ledger, compute_ratio
from . import refinance
from . import killswitch
from .providers import make_working_provider, make_risk_pct_provider

__all__ = [
    "position_fraction", "leg_qty", "make_sizing_callback",
    "count_open_legs", "slots_free", "can_place_leg", "admissible_legs",
    "Ledger", "compute_ratio", "refinance", "killswitch",
    "make_working_provider", "make_risk_pct_provider",
]
