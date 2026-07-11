# -*- coding: utf-8 -*-
"""scout.universe — Этап A: резолв вселенной + модель СОСТОЯТЕЛЬНОСTI (жёсткие отсевы + скор 0–100).

Это фильтр КАЧЕСТВА монеты (ликвидность/зрелость/вола/спред/funding — §D плана, в духе R1), НЕ обещание
прибыли (скан находит СТРУКТУРУ отдельно, под-шаг 3). Пороги ЖЁСТКИХ ОТСЕВОВ — из scout.config (крутилки
владельца); веса/шкалы компонент скора — в сигнатурах score_* (v1-дефолты §D). Чистые функции
(score/hard_rejects/_quantile/…) тестируются на фикстурах без сети; build_universe — тонкий оркестратор
поверх PublicMarket.
"""
import math

import scout.config as scfg

# Стейбл-базы: исключаются на этапе вселенной (решение владельца 2026-07-07 «без стейблкоинов»).
STABLE_BASES = {
    "USDC", "USDE", "DAI", "FDUSD", "TUSD", "USDD", "USTC", "PYUSD", "GUSD",
    "USDP", "SUSD", "EURT", "EUR", "EURS", "USD1", "USDR", "USDX", "FRAX", "LUSD", "USDG",
}

# Bybit interval-коды по нашему ТФ-имени.
_TF_INTERVAL = {"4h": "240", "1h": "60", "5m": "5", "15m": "15"}


def tf_to_interval(tf):
    """'4h'→'240', '1h'→'60', … (Bybit-коды). Неизвестный ТФ → как есть (может быть уже код)."""
    return _TF_INTERVAL.get(tf, tf)


def base_of(symbol):
    """База символа USDT-перпа: 'BTCUSDT'→'BTC', '1000PEPEUSDT'→'1000PEPE'."""
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def is_stablecoin(symbol):
    """Стейбл-к-стейблу пара (база в STABLE_BASES) — исключаем из вселенной."""
    return base_of(symbol) in STABLE_BASES


def _f(x):
    """Мягкий float: None/'' /мусор → None (без исключений)."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _quantile(vals, q):
    """Квантиль q∈[0,1] линейной интерполяцией (как numpy 'linear'); None-элементы отброшены; пусто → None."""
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    if lo + 1 >= len(xs):
        return xs[-1]
    return xs[lo] + (pos - lo) * (xs[lo + 1] - xs[lo])


def range_pcts(klines):
    """Размах баров в % от open: (high−low)/open×100 (та же метрика силы, что mb в детекторе)."""
    return [(k["high"] - k["low"]) / k["open"] * 100.0
            for k in (klines or []) if k.get("open")]


def quantiles_from_klines(klines):
    """(P75, P90) размаха баров в % — волатильность СЕРИИ для калибровки баров (Этап A, любой ТФ). Пусто → (None, None)."""
    rp = range_pcts(klines)
    if not rp:
        return None, None
    return _quantile(rp, 0.75), _quantile(rp, 0.90)


# ── компоненты скора (чистые, монотонные, ограниченные весом) ────────────────
def score_turnover(t, w=30.0, lo=5e6, hi=5e8):
    """Оборот 24h по log-шкале: $5M→0, $500M+→полный вес."""
    if t is None or t <= lo:
        return 0.0
    if t >= hi:
        return w
    return w * math.log10(t / lo) / math.log10(hi / lo)


def score_maturity(age_days, w=25.0, lo=180, hi=1095):
    """Зрелость листинга по ВОЗРАСТУ (дни): молодой порог 180д→0, ~3 года (1095)→полный вес («прошла медведя-2022»).
    Возраст — из launchTime (реальный многолетний), а НЕ из nbars: klines капнуты 1000/запрос (§F, 1 запрос) →
    nbars не различает годовалую и 5-летнюю монету. nbars остаётся жёстким отсевом «есть ли данные» (short_history<300)."""
    if age_days is None or age_days <= lo:
        return 0.0
    if age_days >= hi:
        return w
    return w * (age_days - lo) / (hi - lo)


def score_volatility(p75, w=20.0):
    """Вола P75(range%): плато полного веса в окне «сборщика волы» [1.5%..5%]; спад к 0 на 0.5% и 9%."""
    if p75 is None:
        return 0.0
    if 1.5 <= p75 <= 5.0:
        return w
    if p75 < 1.5:
        return w * max(0.0, (p75 - 0.5) / 1.0)
    return w * max(0.0, (9.0 - p75) / 4.0)


def score_spread(sp, w=15.0, lo=0.03, hi=0.15):
    """Спред (ask−bid)/mid, %: ≤0.03%→полный, ≥0.15%→0 (стопы/тейки едят край)."""
    if sp is None:
        return 0.0
    if sp <= lo:
        return w
    if sp >= hi:
        return 0.0
    return w * (hi - sp) / (hi - lo)


def score_funding(fr_pct, w=10.0, lo=0.01, hi=0.10):
    """|funding|, %/8ч: ≤0.01%→полный, ≥0.1%→0 (высокий funding — драг для лонга). Прокси: текущий рейт
    (медиана-30д — уточнение позже; §D)."""
    if fr_pct is None:
        return 0.0
    a = abs(fr_pct)
    if a <= lo:
        return w
    if a >= hi:
        return 0.0
    return w * (hi - a) / (hi - lo)


def score(m):
    """Скор состоятельности 0–100 (сумма компонент) + разбор по метрикам. m — dict build_metrics."""
    br = {
        "turnover": round(score_turnover(m.get("turnover")), 2),
        "maturity": round(score_maturity(m.get("age_days")), 2),
        "volatility": round(score_volatility(m.get("p75_range")), 2),
        "spread": round(score_spread(m.get("spread_pct")), 2),
        "funding": round(score_funding(m.get("funding_pct")), 2),
    }
    return round(sum(br.values()), 2), br


def hard_rejects(m):
    """Жёсткие отсевы (§D): список причин; пусто = монета годна к скорингу. Пороги — из scout.config."""
    r = []
    if m.get("status") != "Trading":
        r.append("not_trading")
    if m.get("settle") != "USDT":
        r.append("not_usdt")
    if m.get("is_stable"):
        r.append("stablecoin")
    t = m.get("turnover")
    if t is None or t < scfg.SCOUT_MIN_TURNOVER_USD:
        r.append("low_turnover")
    nb = m.get("nbars")
    if nb is None or nb < scfg.SCOUT_MIN_HISTORY_BARS:
        r.append("short_history")
    age = m.get("age_days")
    if age is not None and age < scfg.SCOUT_MIN_AGE_DAYS:
        r.append("young_listing")
    sp = m.get("spread_pct")
    if sp is not None and sp > scfg.SCOUT_MAX_SPREAD_PCT:
        r.append("wide_spread")
    return r


def build_metrics(symbol, inst, tk, klines, now_ms):
    """Собрать метрики монеты из instrument + ticker + klines (klines может быть None = не тянули)."""
    bid, ask = _f(tk.get("bid1Price")), _f(tk.get("ask1Price"))
    spread_pct = None
    if bid and ask and bid > 0 and ask > 0 and ask >= bid:   # ask<bid = скрещённый/битый стакан → невалид (не полный скор)
        mid = (bid + ask) / 2.0
        if mid > 0:
            spread_pct = (ask - bid) / mid * 100.0
    funding = _f(tk.get("fundingRate"))
    age_days = None
    lt = _f(inst.get("launchTime"))
    if lt and lt > 0:
        age_days = (now_ms - lt) / 86_400_000.0
    rp = range_pcts(klines)
    return {
        "symbol": symbol,
        "status": inst.get("status"),
        "settle": inst.get("settleCoin"),
        "is_stable": is_stablecoin(symbol),
        "turnover": _f(tk.get("turnover24h")),
        "last": _f(tk.get("lastPrice")),
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "funding_pct": round(funding * 100.0, 5) if funding is not None else None,
        "age_days": round(age_days, 1) if age_days is not None else None,
        "nbars": len(klines) if klines else 0,
        "p75_range": round(_quantile(rp, 0.75), 4) if rp else None,
        "p90_range": round(_quantile(rp, 0.90), 4) if rp else None,
    }


def _turnover_key(tk):
    v = _f(tk.get("turnover24h"))
    return v if v is not None else 0.0


def build_universe(market, *, universe_max=None, cal_bars=None, interval=None, now_ms, log=print, fetch_series=None):
    """Оркестратор Этапа A: instruments + tickers (батч) → кандидаты (linear USDT-перп) → топ-`universe_max`
    по обороту тянут klines (экономия REST) → метрики+отсевы+скор. Возвращает список per-symbol dict
    {symbol, score, rejects, breakdown, metrics}. RateLimitBan (403) — пробрасываем (circuit-breaker).
    `fetch_series(symbol)` — опц. поставщик серии (Этап A подаёт кэш-докач scout.klines_cache.top_up;
    None ⇒ прямой market.get_klines — путь юнит-тестов)."""
    universe_max = scfg.SCOUT_UNIVERSE_MAX if universe_max is None else universe_max
    cal_bars = scfg.SCOUT_CAL_BARS if cal_bars is None else cal_bars
    interval = tf_to_interval(scfg.SCOUT_TF) if interval is None else interval

    instruments = {i.get("symbol"): i for i in market.get_instruments() if i.get("symbol")}
    tickers = {t.get("symbol"): t for t in market.get_tickers() if t.get("symbol")}

    # кандидаты = линейные USDT-перпы (settleCoin USDT, символ *USDT), СТЕЙБЛЫ исключены НА ЭТАПЕ вселенной
    # (§C/§D: иначе высокооборотный USDCUSDT занял бы klines-запрос и слот топ-N, вытеснив реальную монету).
    perps = [s for s, i in instruments.items()
             if i.get("settleCoin") == "USDT" and s.endswith("USDT")]
    cand = [s for s in perps if not is_stablecoin(s)]
    stables = [s for s in perps if is_stablecoin(s)]
    cand.sort(key=lambda s: _turnover_key(tickers.get(s, {})), reverse=True)
    fetch, beyond = cand[:universe_max], cand[universe_max:]
    log(f"  вселенная: {len(instruments)} инстр. → {len(perps)} USDT-перпов "
        f"(−{len(stables)} стейбл) → топ-{len(fetch)} по обороту (klines)")

    rows = []
    for s in fetch:
        klines = None
        try:
            klines = fetch_series(s) if fetch_series else market.get_klines(s, interval, cal_bars)
        except RateLimitBan:
            raise
        except Exception as e:                          # сеть/сбой одной монеты — не роняем весь прогон
            log(f"  klines {s} FAIL: {e}")
        m = build_metrics(s, instruments.get(s, {}), tickers.get(s, {}), klines, now_ms)
        rej = hard_rejects(m)
        sc, br = (0.0, {}) if rej else score(m)
        rows.append({"symbol": s, "score": sc, "rejects": rej, "breakdown": br, "metrics": m})

    # монеты за пределами cap: klines не тянем (экономия), но фиксируем честно в воронке
    for s in beyond:
        m = build_metrics(s, instruments.get(s, {}), tickers.get(s, {}), None, now_ms)
        rows.append({"symbol": s, "score": 0.0, "rejects": ["beyond_universe_cap"],
                     "breakdown": {}, "metrics": m})
    # стейблы: klines не тянем, фиксируем как отсеянные (§D)
    for s in stables:
        m = build_metrics(s, instruments.get(s, {}), tickers.get(s, {}), None, now_ms)
        rows.append({"symbol": s, "score": 0.0, "rejects": ["stablecoin"],
                     "breakdown": {}, "metrics": m})
    return rows
