"""screener — чистое ядро подбора по параметрам (С7-2а). Без сети и без vendor.

Проверяем: перевод дней в бары по ТФ, импульс-отношение (спайк/плоско/края/None), порог k,
и разбор select_candidates (Этап A отсекает раньше импульса; selected = A-ok И импульс).
"""

from app.screener import (
    bars_for_days,
    has_impulse,
    impulse_ratio,
    select_candidates,
    volumes_of,
)


def test_bars_for_days_per_tf():
    assert bars_for_days(14, "4h") == 84      # 14д × 6 баров/сутки
    assert bars_for_days(14, "1h") == 336     # 14д × 24
    assert bars_for_days(1, "4h") == 6
    assert bars_for_days(0, "4h") == 1        # минимум 1 бар
    assert bars_for_days(14, "неизвестный") == 84  # фолбэк как 4h


def test_volumes_of_extracts_volume():
    kl = [{"open": 1, "volume": 10.0}, {"open": 2, "volume": 20.0}]
    assert volumes_of(kl) == [10.0, 20.0]
    assert volumes_of(None) == []


def test_impulse_ratio_spike():
    # среднее предыдущих = 10, последний = 30 → отношение 3.0
    vols = [10.0] * 10 + [30.0]
    assert impulse_ratio(vols, lookback_bars=10) == 3.0


def test_impulse_ratio_flat_is_one():
    vols = [10.0] * 20
    assert impulse_ratio(vols, lookback_bars=10) == 1.0


def test_impulse_ratio_window_limits_lookback():
    # предыдущие [1,1,1,1,100], последний=10; окно 2 → среднее по [1,100]=50.5 → 10/50.5
    vols = [1.0, 1.0, 1.0, 1.0, 100.0, 10.0]
    assert impulse_ratio(vols, lookback_bars=2) == 10.0 / 50.5
    # окно 4 → среднее по [1,1,1,100]=25.75
    assert impulse_ratio(vols, lookback_bars=4) == 10.0 / 25.75


def test_impulse_ratio_insufficient_or_bad():
    assert impulse_ratio([], lookback_bars=10) is None
    assert impulse_ratio([5.0], lookback_bars=10) is None      # только один бар
    assert impulse_ratio([0.0, 0.0, 5.0], lookback_bars=10) is None  # среднее предыдущих = 0
    assert impulse_ratio([None, None, 5.0], lookback_bars=10) is None  # предыдущие пусты
    assert impulse_ratio([10.0, 10.0, None], lookback_bars=10) is None  # последний пуст


def test_has_impulse_threshold():
    spike = [10.0] * 10 + [16.0]     # ratio 1.6
    weak = [10.0] * 10 + [14.0]      # ratio 1.4
    assert has_impulse(spike, k=1.5, lookback_bars=10) is True
    assert has_impulse(weak, k=1.5, lookback_bars=10) is False
    assert has_impulse(weak, k=1.3, lookback_bars=10) is True   # ниже порог — проходит


def _row(symbol, rejects):
    return {"symbol": symbol, "rejects": rejects, "metrics": {}}


def test_select_candidates_full_breakdown():
    rows = [
        _row("AAAUSDT", []),                    # Этап A ок + импульс есть → selected
        _row("BBBUSDT", []),                    # Этап A ок, импульса нет → не selected
        _row("CCCUSDT", ["low_turnover"]),      # отсеян Этапом A → импульс не считаем
    ]
    vols = {
        "AAAUSDT": [{"volume": 10.0}] * 10 + [{"volume": 30.0}],   # ratio 3.0
        "BBBUSDT": [{"volume": 10.0}] * 11,                        # ratio 1.0
    }
    res = {r["symbol"]: r for r in select_candidates(rows, k=1.5, days=1, tf="4h",
                                                     klines_of=lambda s: vols.get(s))}

    assert res["AAAUSDT"]["selected"] is True
    assert res["AAAUSDT"]["impulse_ratio"] == 3.0
    assert res["AAAUSDT"]["stage_a_ok"] is True

    assert res["BBBUSDT"]["selected"] is False
    assert res["BBBUSDT"]["impulse_ok"] is False
    assert res["BBBUSDT"]["impulse_ratio"] == 1.0

    # отсеянный Этапом A: импульс НЕ считается (ratio None), в кандидаты не идёт
    assert res["CCCUSDT"]["stage_a_ok"] is False
    assert res["CCCUSDT"]["rejects"] == ["low_turnover"]
    assert res["CCCUSDT"]["impulse_ratio"] is None
    assert res["CCCUSDT"]["selected"] is False


def test_select_candidates_no_klines_provider():
    # без klines_of импульс не посчитать → никто не selected, но разбор Этапа A честный
    rows = [_row("AAAUSDT", []), _row("BBBUSDT", ["young_listing"])]
    res = {r["symbol"]: r for r in select_candidates(rows, klines_of=None)}
    assert res["AAAUSDT"]["stage_a_ok"] is True
    assert res["AAAUSDT"]["selected"] is False
    assert res["BBBUSDT"]["stage_a_ok"] is False
