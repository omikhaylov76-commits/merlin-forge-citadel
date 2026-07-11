# -*- coding: utf-8 -*-
"""execution.protection — инвариант покрытия стопа (Веха 5.7 под-шаг 1, keystone-1).

Гарантия «у открытой позиции всегда есть стоп на весь размер»: либо позиционный вшитый
Full-стоп (stopLoss>0 — покрывает весь net), либо пуловые пер-ножные условные -stp, чья
суммарная qty >= net. Чистые функции (без брокера/IO/состояния). Re-arm (set_trading_stop
по stop0 карточки) делает вызывающий (app.main._ensure_stop_coverage) под LIVE-гейтом.

Зачем: «никогда не голый» до 5.7 было СЛЕДСТВИЕМ порядка действий, а не проверкой. Один узкий
случай его ломал: миграция бегунка в БУ снимает Full, а пуловые -stp считаются от qty карточки —
если карта занижена (частичный залив в простое), пул покрывает < net → голый остаток. Этот
инвариант делает покрытие ПРОВЕРЯЕМЫМ и восстанавливает Full-стоп, если позиция без покрытия.
"""

_TOL = 1e-9


def sum_stop_qty(stop_orders, prefix, symbol):
    """Σ qty НАШИХ стоящих reduce-only -stp условных символа (по префиксу+суффиксу orderLinkId).
    stop_orders — список dict от broker.get_open_orders(symbol, order_filter='StopOrder')."""
    pfx = f"{prefix}-{symbol}-"
    total = 0.0
    for o in stop_orders:
        link = o.get("orderLinkId") or ""
        if link.startswith(pfx) and link.endswith("-stp"):
            try:
                total += float(o.get("qty") or 0)
            except (TypeError, ValueError):
                continue
    return total


def is_covered(net, stop_loss, stop_qty, *, tol=_TOL):
    """True, если ЛОНГ-позиция net защищена: net≈0 (нечего защищать) ИЛИ позиционный Full stopLoss>0
    (покрывает весь net) ИЛИ Σ пул -stp qty >= net−tol. False ⇒ вызывающий ставит Full-стоп по stop0."""
    if net <= tol:
        return True
    if stop_loss is not None and float(stop_loss) > 0:
        return True
    return stop_qty >= net - tol
