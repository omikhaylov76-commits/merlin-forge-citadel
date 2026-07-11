# -*- coding: utf-8 -*-
"""scout.klines_cache — ROLLING кэш свечей в БД (Веха 7, под-шаг 2b, решение владельца 2026-07-08).

Держим свечи в `scout_klines`, катим скользящее окно: залить один раз → докачивать ТОЛЬКО новые бары →
прунить старше ретеншна. Скан (под-шаг 3) и график (5b) читают из БД (`read_window`), биржу не дёргают.
Размер крошечный (200 монет × 1000 баров × 4h ≈ 30 МБ). Инкрементальный докач САМОЛЕЧИТ разрыв: если кэш
отстал на K баров, тянем ~K (до `want`), upsert идемпотентен (перекрытие не дублит) → дыр в окне нет.
"""
import time

from scout import universe as uni

# длительность бара по имени ТФ (мс) — для оценки разрыва при инкрементальном докаче
_TF_MS = {"4h": 14_400_000, "1h": 3_600_000, "15m": 900_000, "5m": 300_000}


def bar_ms(tf):
    return _TF_MS.get(tf, 14_400_000)


def top_up(db, market, symbol, tf, want, *, retention=None, now_ms=None):
    """Докачать кэш (symbol,tf) и вернуть окно последних `want` свечей (хронология).

    Пустой кэш → тянем `want` баров (bootstrap). Иначе — хвост, покрывающий разрыв с последнего бара
    (самолечение до `want`; при актуальном кэше — ~2-3 бара). Upsert идемпотентен; прунинг до `retention`
    (дефолт = want). `RateLimitBan` (403) пробрасываем наверх (circuit-breaker). Возвращает list свечей."""
    retention = want if retention is None else retention
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    interval = uni.tf_to_interval(tf)
    last = db.scout_klines_last_ms(symbol, tf)
    if last is None:
        fetch_n = want
    else:
        gap_bars = int((now_ms - last) / bar_ms(tf)) + 2      # +буфер; самолечение разрыва
        fetch_n = max(2, min(want, gap_bars))
    candles = market.get_klines(symbol, interval, fetch_n)     # RateLimitBan пробрасывается
    if candles:
        db.scout_klines_put_many(symbol, tf, candles)
        db.scout_klines_prune(symbol, tf, retention)
    return db.scout_klines_read_window(symbol, tf, want)


def read_window(db, symbol, tf, n):
    """Последние n свечей (symbol,tf) из кэша в хронологии (для скана/графика; биржу НЕ дёргаем)."""
    return db.scout_klines_read_window(symbol, tf, n)
