# -*- coding: utf-8 -*-
"""market.klines_4h — источник 4h-серий (сигнал) + детект закрытия 4h-бара.

Веха 5 фича 5.2 под-шаг 2. Сигнал V8.1 ищется на ЗАКРЫТИИ 4h-бара (docs/12, гибрид
4h-сигнал / 15m-исполнение). Здесь — два чистых строительных блока, которые под-шаг 3
свяжет в торговый цикл:

  • fetch_4h_series(broker, symbol) — закрытые 4h-свечи (ASC) с биржи: сброс форм-свечи
    (как market_data._closed_klines), fail-safe на ошибке/коротком окне → None
    (= «нет годных данных, этот цикл НЕ торгуем»). Страж длины закрывает дыру find_signal,
    который не проверяет прогрев EMA200 (signal._ema_gate: короткая серия → NaN-EMA молча
    «пропускает», ломая parity). Полная серия → тёплая EMA == движок.

  • is_4h_close(open_ms) — закрывает ли 15m-свеча 4h-период (правая граница на 00/04/08/
    12/16/20 UTC). Чистая арифметика по open-time в МИЛЛИСЕКУНДАХ (Bybit отдаёт мс).

Свеча = формат get_klines: {time(ms open-time), open, high, low, close, volume} (floats).
Чистый модуль: без БД/состояния/курсора (в отличие от 15m MarketData — 4h тянем свежим
окном каждый цикл; find_signal всё равно пересчитывает EMA на полной серии). Без сети/ордеров.
"""
import config
from logging_.trade_logger import get_logger

FOUR_HOUR_MS = 4 * 3600 * 1000      # 14_400_000 — период 4h в мс
FIFTEEN_MIN_MS = 15 * 60 * 1000     # 900_000 — шаг 15m-свечи в мс (до правой границы)

# ПОЛ прогрева EMA200 для тонких монет: 3×period ≈ 6 постоянных времени EMA (rel_err vs EMA200
# движка на полной истории ~1.8e-4 ≪ 1e-3 даже на полу; 2×period=400 давал 1.19e-3 — мало).
# В ПРОДЕ обычно кормим SIGNAL_KLINE_LIMIT-1 (~999) баров → rel_err ~1e-7 ≈ движок; пол бьёт лишь
# для монет с <600 закрытых 4h. Остаток на полу (граничный бар тренд-фильтра) — в parity-гейт п.3.
# Движок: ewm span=200 adjust=False (port_lib._ema:67). Меньше порога → fetch_4h_series → None.
MIN_4H_BARS = 3 * config.strategy.EMA_PERIOD     # 600


def is_4h_close(open_ms, step_ms=FIFTEEN_MIN_MS):
    """True, если бар с open-time open_ms (мс) ЗАКРЫВАЕТ 4h-период.

    Правая граница бара = open_ms + step_ms; закрытие 4h-периода ⇔ она кратна 4h (UTC).
    step_ms по умолчанию = 15m (шаг исполнения). Целочисленная арифметика — точно, без float.
    Срабатывает ровно на 00/04/08/12/16/20 UTC и нигде внутри.
    """
    return (int(open_ms) + step_ms) % FOUR_HOUR_MS == 0


def fetch_4h_series(broker, symbol, *, limit=None, min_bars=None, logger=None):
    """Закрытые 4h-свечи по символу (ASC, формат get_klines) или None.

    Тянет get_klines(interval=config.ops.INTERVAL='240'), СБРАСЫВАЕТ форм-свечу (последнюю,
    как market_data._closed_klines). Возвращает None (fail-safe «не торгуем этот цикл») если:
      • ошибка брокера / пустой ответ (get_klines НЕ оборачивает исключения — ловим здесь);
      • закрытых баров < min_bars (по умолчанию MIN_4H_BARS) → EMA200 не прогрета (parity).
    Иначе — список закрытых 4h-свечей. БЕЗ состояния: свежее окно каждый вызов.
    """
    log = logger or get_logger("pifagor.klines4h")
    lim = limit if limit is not None else config.ops.SIGNAL_KLINE_LIMIT
    need = min_bars if min_bars is not None else MIN_4H_BARS
    try:
        rows = broker.get_klines(symbol, interval=config.ops.INTERVAL, limit=lim)
    except Exception as e:   # сеть/биржа: fail-safe — нет данных, цикл не торгуем
        log.warning("%s: 4h-серия недоступна (%s) → пропуск цикла", symbol, e)
        return None
    if not rows or len(rows) < 2:
        log.warning("%s: 4h-серия пуста/коротка (%d свечей) → пропуск цикла",
                    symbol, len(rows) if rows else 0)
        return None
    closed = rows[:-1]            # сбросить незакрытую (форм) свечу
    if len(closed) < need:
        log.warning("%s: 4h-серия %d < %d (EMA200 не прогрета) → пропуск цикла",
                    symbol, len(closed), need)
        return None
    return closed
