# -*- coding: utf-8 -*-
"""scout.bars — Этап A: калибровка баров mb1/mb2 (volnorm-v1) + курирование СПИСКА.

ЧЕСТНЫЙ метод (капкан R3 — НЕ подбор «лучших баров» per coin, который даёт look-ahead #7 / инфляцию Calmar):
бар = K × квантиль волатильности монеты, где K — ДВЕ ГЛОБАЛЬНЫЕ константы (не per-coin), откалиброванные
воспроизводить БОЕВЫЕ бары на РАБОЧЕМ окне (§E). Боевые монеты (COINS_CONFIG) берут свои боевые бары
(бейдж «config»); незнакомые — volnorm (бейдж «volnorm-v1» = generic, НЕ проверено held-out).
Курирование: годные строки вселенной по скору → топ-`SCOUT_LIST_MAX` со скором ≥ `SCOUT_MIN_SCORE` → scout_list.
"""
import config
import scout.config as scfg
from scout import universe as uni

# K1/K2 — глобальные константы volnorm-v1 (§E). Замер median(боевой_бар / квантиль_волы) на РАБОЧЕМ окне
# 1000 баров по 16 боевым монетам (data/): K1=0.776, K2=0.951 → рабочие 0.78/0.95. ⚠ На ПОЛНОЙ истории было
# 0.56/0.66, но окно ОЦЕНКИ обязано совпадать с окном ПРИМЕНЕНИЯ (фикс аудита): недавняя вола ниже → K выше;
# 0.6/0.7 систематически занижали бы бары в текущем режиме. K наследуют смещение боевых баров (перф-отбор R3) —
# честная оговорка в бейдже «не held-out».
K1 = 0.78
K2 = 0.95

_FLOOR_MB1 = 1.5      # «строгость = эдж» (R1/R3: ниже 1.5 — токсичная зона)
_MAX_MB1 = 3.5
_MIN_MB2 = 2.5
_MAX_MB2 = 6.0
_SNAP = 0.25


def _snap(x, step=_SNAP):
    return round(x / step) * step


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def volnorm_bars(p75, p90, k1=K1, k2=K2):
    """Generic-бары от волатильности: mb1=clamp(snap(K1·P75), 1.5, 3.5); mb2=clamp(snap(K2·P90), max(2.5,mb1+0.5), 6.0).
    Нет квантилей (None) → консервативный пол (1.5, 2.5)."""
    if p75 is None or p90 is None:
        return _FLOOR_MB1, _MIN_MB2
    mb1 = _clamp(_snap(k1 * p75), _FLOOR_MB1, _MAX_MB1)
    mb2 = _clamp(_snap(k2 * p90), max(_MIN_MB2, mb1 + 0.5), _MAX_MB2)
    return mb1, mb2


def bars_for(symbol, p75, p90, tf="4h"):
    """Бары монеты + источник для ТФ `tf`. 4h: боевая (в COINS_CONFIG) → её бары ('config'); иначе volnorm-v1.
    НЕ-4h (1h, …): боевые бары COINS_CONFIG откалиброваны под 4h-свечи → НЕ применимы на другом ТФ → ВСЕГДА
    volnorm-v1 (честный бейдж generic, не held-out). Под-шаг 7."""
    if tf == "4h":
        cfg = config.strategy.COINS_CONFIG.get(symbol)
        if cfg and cfg.get("mb1") is not None and cfg.get("mb2") is not None:
            return float(cfg["mb1"]), float(cfg["mb2"]), "config"
    mb1, mb2 = volnorm_bars(p75, p90)
    return mb1, mb2, "volnorm-v1"


def bars_from_series(series, symbol, tf):
    """Бары монеты из СЕРИИ свечей ТФ `tf` (Этап A, per-ТФ калибровка, под-шаг 7). Квантили P75/P90 берутся
    из СВОЕЙ серии (ТФ-агностично by design). Возврат {mb1, mb2, bar_source} или None (пустая серия)."""
    if not series:
        return None
    p75, p90 = uni.quantiles_from_klines(series)
    mb1, mb2, src = bars_for(symbol, p75, p90, tf)
    return {"mb1": mb1, "mb2": mb2, "bar_source": src}


def curate_list(rows, *, list_max=None, min_score=None):
    """Курированный список из строк вселенной: годные (без отсевов) со скором ≥ min_score, по убыванию скора,
    топ-list_max, с барами (config|volnorm-v1). Возвращает list[dict] {symbol, score, mb1, mb2, bar_source,
    breakdown, metrics}. Пол+кап — решение владельца (топ-200 + пол 35, §D/§O)."""
    list_max = scfg.SCOUT_LIST_MAX if list_max is None else list_max
    min_score = scfg.SCOUT_MIN_SCORE if min_score is None else min_score
    passed = [r for r in rows if not r["rejects"] and r["score"] >= min_score]
    passed.sort(key=lambda r: r["score"], reverse=True)
    out = []
    for r in passed[:list_max]:
        m = r["metrics"]
        mb1, mb2, src = bars_for(r["symbol"], m.get("p75_range"), m.get("p90_range"))
        out.append({"symbol": r["symbol"], "score": r["score"], "mb1": mb1, "mb2": mb2,
                    "bar_source": src, "breakdown": r["breakdown"], "metrics": m})
    return out
