# -*- coding: utf-8 -*-
"""market.market_data — маркет-данные (15m-исполнение).

Веха 3 фича 2: класс MarketData тянет свежие ЗАКРЫТЫЕ 15m-свечи по монете через
broker.get_klines, держит in-memory дедуп-курсор (last_seen) и rolling-буфер закрытых
свечей (окно под lifecycle, фича 3). Плюс заглушка check_utc_alignment (полная 4h-проверка
UTC-границ — отдельный пункт Вехи 3) и чистая next_boundary_ms для выравнивания цикла.

Парити: разрешение ведения = 15m, не мельче (docs/05, ADR 0006). Свеча = формат get_klines:
{time(ms open-time), open, high, low, close, volume} (floats). Дедуп-ключ — time (open-time).
"""
import config
from logging_.trade_logger import get_logger


def check_utc_alignment(bars=None, logger=None):
    """Заглушка Вехи 1. Возвращает True (не блокирует). Полная 4h-проверка — Веха 3."""
    msg = "check_utc_alignment: заглушка (полная проверка 4h-границ UTC — Веха 3)"
    if logger is not None:
        logger.warning(msg)
    return True


def interval_ms():
    """15m-интервал исполнения в миллисекундах из config (один источник правды)."""
    return int(config.ops.EXEC_INTERVAL) * 60_000


def next_boundary_ms(now_ms, step_ms):
    """Время СЛЕДУЮЩЕЙ границы интервала (мс) от now_ms. Чистая функция (тестируемая).
    На точной границе возвращает следующую (строго > now_ms) — буфер сна добавляет цикл."""
    return (now_ms // step_ms + 1) * step_ms


class MarketData:
    """Подтягивание закрытых 15m-свечей по монете с дедупом и rolling-буфером.

    Состояние in-memory: last_seen[symbol] = open-time последней эмитнутой закрытой свечи;
    bars[symbol] = окно закрытых 15m-свечей (под lifecycle, фича 3). При рестарте состояние
    теряется → первый вызов по символу ПРАЙМИТ курсор без эмиссии (как боевой V7
    legacy_bot_reference/main.py:337-343 — не отрабатываем стартовый бар). Персистентность
    дедупа — state/lifecycle (фичи 3/5).
    """

    def __init__(self, broker, logger=None):
        self.broker = broker
        self.log = logger or get_logger("pifagor.market")
        self.last_seen = {}   # symbol -> ms (open-time последней эмитнутой закрытой свечи)
        self.bars = {}        # symbol -> [candle, ...] закрытые 15m-свечи (rolling-окно)

    def _closed_klines(self, symbol):
        """Закрытые 15m-свечи (ASC) без форм-свечи. get_klines уже сортирует ASC, поэтому
        последняя — текущая незакрытая (форм) свеча → сбрасываем rows[:-1]. <2 свечей → []."""
        rows = self.broker.get_klines(
            symbol, interval=config.ops.EXEC_INTERVAL, limit=config.ops.EXEC_KLINE_LIMIT,
        )
        if not rows or len(rows) < 2:
            return []
        return rows[:-1]   # сбросить незакрытую (форм) свечу

    def latest_closed(self, symbol):
        """Последняя ЗАКРЫТАЯ 15m-свеча (или None). Чистое чтение — НЕ трогает last_seen/bars.
        Для смоука/лога (показать свечу), НЕ для торгового пути."""
        closed = self._closed_klines(symbol)
        return closed[-1] if closed else None

    def fetch_new_closed(self, symbol):
        """Новые ЗАКРЫТЫЕ 15m-свечи строго новее last_seen[symbol] (дедуп по open-time).

        Первый вызов по символу = ПРАЙМ: ставит курсор на последнюю закрытую и возвращает []
        (V7-безопасность — не ловим стартовый бар). Дальше — только строго возрастающие по time
        и новее курсора (защита от дублей в ответе). Обновляет bars[symbol] и
        last_seen[symbol]=max(эмитнутых). Детект пропуска свечей (простой цикла) → WARN.
        При пустом/коротком ответе API bars[symbol] сохраняет последнее валидное окно
        (намеренно — окно переживает сетевой сбой, lifecycle не остаётся без истории).
        """
        closed = self._closed_klines(symbol)
        if not closed:
            return []   # bars[symbol] не трогаем — держим последнее валидное окно
        self.bars[symbol] = closed   # rolling-окно (под lifecycle, фича 3)

        last = self.last_seen.get(symbol)
        if last is None:
            self.last_seen[symbol] = closed[-1]["time"]   # прайм без эмиссии
            return []

        new, prev = [], last
        for c in closed:
            if c["time"] > prev:        # строго возрастающие и новее курсора
                new.append(c)
                prev = c["time"]
        if not new:
            return []

        gap = (new[0]["time"] - last) // interval_ms()
        if gap > 1:
            self.log.warning(
                "%s: пропущено ~%d 15m-свечей (простой цикла); бэкафилл сверх окна — хвост",
                symbol, gap - 1,
            )
        self.last_seen[symbol] = prev    # = max(time эмитнутых)
        return new
