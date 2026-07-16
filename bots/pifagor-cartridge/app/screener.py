"""screener — С7-2а: подбор монет по ПАРАМЕТРАМ (не фикс-список) для разового прогона.

Возраст и оборот 24h — это уже штатные отсевы Этапа A вендора (`universe.build_universe`:
`age_days` из launchTime → `young_listing`; `turnover24h` → `low_turnover`). НОВОЕ здесь —
ИМПУЛЬС: всплеск объёма последнего бара против обычного. Цель Оператора — «монеты, в которых
есть импульс».

Чистые функции (impulse_ratio / has_impulse / select_candidates) — юнит-тест без сети и без vendor.
Живой оркестратор (build_universe → импульс → scan_list на оба ТФ → отчёт) тянет Bybit и связан с БД
Этапа A — он за гейтом (риск 403-бана на общем IP скаута + развилка изоляции БД), пишется отдельно.
Vendor НЕ правим — только импорт функций образца.
"""
from __future__ import annotations

# Сколько баров ТФ укладывается в сутки — для перевода «N дней» в размер окна среднего объёма.
_BARS_PER_DAY = {"4h": 6, "1h": 24, "15m": 96, "5m": 288}


def bars_for_days(days: float, tf: str) -> int:
    """Число баров ТФ за `days` суток (окно среднего объёма). Неизвестный ТФ считаем как 4h."""
    return max(1, int(round(days * _BARS_PER_DAY.get(tf, 6))))


def volumes_of(klines) -> list:
    """Объёмы из klines (vendor parse_kline_rows кладёт ключ 'volume' в каждый бар)."""
    return [k.get("volume") for k in (klines or [])]


def impulse_ratio(volumes, *, lookback_bars):
    """Отношение объёма ПОСЛЕДНЕГО бара к среднему объёму предыдущих `lookback_bars` баров.

    `volumes` — по возрастанию времени (последний = самый свежий бар). Возвращает None, если данных
    мало, все предыдущие объёмы пусты, или их среднее ≤ 0 (нельзя нормировать)."""
    if not volumes or len(volumes) < 2:
        return None
    recent = volumes[-1]
    if recent is None:
        return None
    start = max(0, len(volumes) - 1 - lookback_bars) if lookback_bars else 0
    prior = [v for v in volumes[start:-1] if v is not None]
    if not prior:
        return None
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return recent / avg


def has_impulse(volumes, *, k=1.5, lookback_bars):
    """Импульс есть, если объём последнего бара ≥ k× среднего объёма предыдущих `lookback_bars`."""
    r = impulse_ratio(volumes, lookback_bars=lookback_bars)
    return r is not None and r >= k


def select_candidates(rows, *, k=1.5, days=14, tf="4h", klines_of=None):
    """Из строк `build_universe` (per-symbol {symbol, rejects, metrics, …}) отобрать кандидатов.

    Кандидат = прошёл Этап A (rejects пуст) И имеет импульс ≥ k. `klines_of(symbol)` отдаёт klines
    для объёма (в живом прогоне — из кэша, что тянул build_universe). Возвращает честный разбор по
    КАЖДОЙ монете (для отчёта «кто взят / кто отсеян и почему»):
    {symbol, stage_a_ok, rejects, impulse_ratio, impulse_ok, selected}."""
    lb = bars_for_days(days, tf)
    out = []
    for row in rows:
        sym = row.get("symbol")
        rej = row.get("rejects") or []
        stage_a_ok = not rej
        # импульс считаем ТОЛЬКО для прошедших Этап A — незачем тянуть/мерить отсеянные
        kl = klines_of(sym) if (stage_a_ok and klines_of) else None
        ratio = impulse_ratio(volumes_of(kl), lookback_bars=lb) if stage_a_ok else None
        imp_ok = ratio is not None and ratio >= k
        out.append({
            "symbol": sym,
            "stage_a_ok": stage_a_ok,
            "rejects": rej,
            "impulse_ratio": round(ratio, 3) if ratio is not None else None,
            "impulse_ok": imp_ok,
            "selected": stage_a_ok and imp_ok,
        })
    return out
