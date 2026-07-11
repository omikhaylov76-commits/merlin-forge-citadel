# -*- coding: utf-8 -*-
"""risk_capital.sizing — РАЗМЕР НОГИ V8.1 (Веха 3).

Чистая математика сайзинга, ЗЕРКАЛО движка-эталона (parity — ЗАКОН). Размер ноги = доля эквити
min(MAX_LEVERAGE, risk%/stopdist%), как в strategy/engine/port_lib.py:128 (compound), где
stopdist% = abs(entry − stop0)/entry × 100 (начальная дистанция стопа, backtest_v4_sim.py:38).
risk% — СЫРОЕ значение крутилки (1.3, НЕ 0.013): процент/процент сокращается в безразмерное плечо.

ТОЛЬКО считает: без config/IO/округления под инструмент (флор к qtyStep + minQty-skip делает
executor.InstrumentMeta — единственное дозволенное расхождение с непрерывным движком). Working-капитал
и крутилки приходят ЧЕРЕЗ провайдеры (шов): на этой вехе — статичный config-сид; живой леджер — Веха 4.
"""


def position_fraction(risk_pct, stopdist_pct, max_leverage=5.0):
    """Доля эквити на ногу — дословный mirror port_lib.compound (port_lib.py:128):
    min(max_leverage, risk_pct / stopdist_pct) при stopdist_pct > 0, иначе max_leverage (клэмп плеча).
    risk_pct и stopdist_pct — В ПРОЦЕНТАХ (1.3, 5.0), отношение безразмерно. Parity-несущая функция."""
    if stopdist_pct > 0:
        return min(max_leverage, risk_pct / stopdist_pct)
    return float(max_leverage)


def leg_qty(working, entry, stop, *, risk_pct, max_leverage=5.0):
    """Объём ноги в монете: (frac × working) / entry, frac = position_fraction(...). RAW (без
    округления под инструмент — это executor). None при вырожденном входе (entry<=0 или stopdist<=0,
    т.е. entry<=stop — невалидная нога: для реальной фибо-сетки не бывает, executor пропустит)."""
    if entry <= 0:
        return None
    stopdist_pct = abs(entry - stop) / entry * 100.0
    if stopdist_pct <= 0:
        return None                                  # entry==stop: вырожденная нога — пропуск (parity-нейтрально)
    frac = position_fraction(risk_pct, stopdist_pct, max_leverage)
    return frac * working / entry


def make_sizing_callback(working_provider, *, risk_pct_provider, max_leverage_for):
    """Фабрика шова executor.sizing: callable(symbol, lv, entry, stop) -> qty|None. Замыкает провайдеры
    (zero-arg working_provider/risk_pct_provider читаются НА ВЫЗОВЕ — крутилка живая; max_leverage_for(symbol)
    — per-coin плечо). Возвращает RAW qty (executor.fix_qty флорит + minQty-skip). Веха 4 подменит провайдеры
    (живой working/леджер, alarm-риск) БЕЗ правок executor/sizing."""
    def sizing(symbol, lv, entry, stop):
        return leg_qty(working_provider(), entry, stop,
                       risk_pct=risk_pct_provider(),
                       max_leverage=max_leverage_for(symbol))
    return sizing
