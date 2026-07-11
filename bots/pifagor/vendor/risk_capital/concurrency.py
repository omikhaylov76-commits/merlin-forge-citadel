# -*- coding: utf-8 -*-
"""risk_capital.concurrency — ГЕЙТ cap=8 V8.1 (Веха 3).

Ограничитель экспозиции: не более CONCURRENCY_CAP одновременно ОТКРЫТЫХ (залитых) ног по ВСЕМУ
портфелю из 10 монет — живой аналог heap len(h) движка (port_lib.compound: сверх капа нога
ПРОПУСКАЕТСЯ, не масштабируется; cap — ограничитель, НЕ рычаг, ADR 0002).

Чистые функции над портфелем in-memory карт сетапов (state не владеют). Слот занимается, когда нога
становится OPEN (залив), освобождается при закрытии — только OPEN, НЕ стоящие лимитки. Место вызова
(перед постановкой) и персист счётчика (рестарт-безопасность) — интеграция Вехи 5 (reconcile, ADR 0008).
"""
from execution.actions import open_legs


def count_open_legs(setups):
    """Σ открытых (state==OPEN) ног по портфелю карт — аналог len(h) движка."""
    return sum(len(open_legs(s)) for s in setups)


def slots_free(setups, cap):
    """Свободные слоты до капа: max(0, cap − открытые ноги)."""
    return max(0, cap - count_open_legs(setups))


def can_place_leg(setups, cap):
    """Есть ли место хотя бы под одну ногу."""
    return slots_free(setups, cap) > 0


def admissible_legs(free_slots, lvs):
    """По-ноговый гейт (D2/инвариант #10): из ног lvs ставим МЕЛКИЕ→ГЛУБОКИЕ, пока есть слоты;
    лишние ГЛУБОКИЕ (большие lv) отбрасываем. free_slots<=0 -> []."""
    if free_slots <= 0:
        return []
    return sorted(lvs)[:free_slots]
