# -*- coding: utf-8 -*-
"""Зонд «греющихся» кандидатов на сетап (bot_health под-шаг 2a).

Зеркалит УСЛОВИЯ боевого детектора detect_v81 (strategy/engine/v81_sim.py), но возвращает ПРОМЕЖУТОЧНОЕ
состояние «толчок-1 был, идёт консолидация под вершиной, ждём пробой» — то, что детектор ещё НЕ оформил в
сигнал. detect_v81 НЕ трогаем: это отдельная read-only функция; гейт паритета `gates()` держит зонд ↔
детектор в синхроне (когда детектор фирит сигнал на баре j, зонд на серии до j обязан был показывать
активного кандидата — иначе зонд «слепнет» на реальном паттерне).

Long-only (боевой v2 shorts off). Это НЕ предсказание прибыли (R2/R4: сборщик волатильности не предсказывает) —
честная СТРУКТУРА «паттерн наполовину сложился». Мульти-bar-1: берём САМЫЙ РАННИЙ активный толчок-1 —
совпадает с forward-scan движка (run_v8 берёт первый непустой detect_v81 сверху вниз по i), чтобы зонд показывал
ТОТ ЖЕ паттерн, что «ловит» бот (ревью 2a: recent давал до 25% мимо на вложенных, напр. DOGE).
"""
from strategy.engine.v81_sim import detect_v81


def forming_candidate(o, h, l, c, *, mb1, retr=0.5, clean_thr=0.5, start_i=1):
    """Самый РАННИЙ активный толчок-1 на закрытой серии (как forward-scan run_v8): вершина ещё НЕ пробита
    и консолидация НЕ отменена — теми же порогами, что detect_v81. Возврат — дескриптор или None (не греется).

    Толчок-1 (long, как detect_v81): rng>0, размах rng/o*100 ≥ mb1, «чистый» (h−c) < clean_thr·rng.
    Активен, пока для всех баров j>i: low ≥ l[i]+retr·rng (нет отмены) И high ≤ h[i] (нет пробоя = ещё под вершиной).
    consolidation_bars=0 → толчок-1 только что (пробой/отмена решатся на следующем баре).
    Дистанции в % от текущей цены (последний close): breakout_dist_pct вверх до вершины, cancel_dist_pct вниз."""
    n = len(c)
    if n < 2:
        return None
    price = c[n - 1]
    if price is None or price <= 0:
        return None
    for i in range(max(int(start_i), 1), n):      # i ВПЕРЁД (как run_v8 — первый непустой detect_v81); последний бар = свежий толчок-1
        rng = h[i] - l[i]
        if not (rng > 0 and o[i] > 0 and rng / o[i] * 100.0 >= mb1 and (h[i] - c[i]) < clean_thr * rng):
            continue                              # не толчок-1 (условие бара-1 detect_v81: сильный+чистый long)
        line = l[i] + retr * rng                  # уровень отмены (откат ≥ retr бара-1)
        active = True
        for j in range(i + 1, n):                 # консолидация: отмена (low<line) ИЛИ пробой (high>hi) → не «forming»
            if l[j] < line or h[j] > h[i]:
                active = False
                break
        if not active:
            continue                              # этот толчок-1 мёртв (отменён/пробит) → ищем следующий (более поздний)
        return {
            "bar1_index": i,
            "consolidation_bars": (n - 1) - i,
            "breakout_level": h[i],
            "breakout_dist_pct": (h[i] - price) / price * 100.0,
            "cancel_level": line,
            "cancel_dist_pct": (price - line) / price * 100.0,
        }
    return None


# ── гейт паритета зонд ↔ detect_v81 (синтетика; те же сценарии, что gates() детектора) ──
def _mk(rows):
    """o/h/l/c из 2 тёплых баров + строк (o,h,l,c) — как gates() детектора (индекс данных с 2)."""
    o = [100.0, 100.0] + [r[0] for r in rows]
    h = [100.5, 100.5] + [r[1] for r in rows]
    l = [99.5, 99.5] + [r[2] for r in rows]
    c = [100.0, 100.0] + [r[3] for r in rows]
    return o, h, l, c


def _trunc(seq, upto):
    return tuple(s[:upto] for s in seq)


def gates():
    """Синтетический гейт паритета зонд ↔ detect_v81. True = синхронны. Печатает пункты (mini-REPL)."""
    ok = True
    MB = 1.0

    # G1: два сильных чистых бара, пробой на индексе 3 (толчок-1 = индекс 2). До пробоя — кандидат виден.
    seq = _mk([(100, 101.5, 100, 101.4), (101.4, 103, 101, 102.9)])
    sig = detect_v81(*seq, 2, mb1=MB, mb2=MB)
    cand = forming_candidate(*_trunc(seq, 3), mb1=MB)             # серия [0..2] — толчок-1 без консолидации
    g1 = (sig is not None and sig[3] == 3 and cand is not None
          and abs(cand["breakout_level"] - 101.5) < 1e-9 and cand["consolidation_bars"] == 0)
    print("  G1 сигнал@3 → до пробоя кандидат есть (breakout_level=101.5):", g1); ok = ok and g1

    # G2: импульс-консолид-консолид-пробой на индексе 5 (толчок-1 = индекс 2). Кандидат в консолидации.
    seq = _mk([(100, 101.5, 100, 101.4), (101.4, 101.4, 100.9, 101.0),
               (101.0, 101.3, 100.85, 101.1), (101.1, 103, 101, 102.9)])
    sig = detect_v81(*seq, 2, mb1=MB, mb2=MB)
    cand = forming_candidate(*_trunc(seq, 5), mb1=MB)            # серия [0..4] — 2 бара консолидации
    g2 = (sig is not None and sig[3] == 5 and cand is not None
          and cand["consolidation_bars"] == 2 and abs(cand["breakout_level"] - 101.5) < 1e-9)
    print("  G2 сигнал@5 → кандидат с consolidation_bars=2:", g2); ok = ok and g2

    # G3: откат >50% в консолидации (толчок-1 отменён на индексе 3) → зонд None, детектор None.
    seq = _mk([(100, 101.5, 100, 101.4), (101.4, 101.3, 100.7, 100.8), (100.8, 103, 101, 102.9)])
    g3 = (detect_v81(*seq, 2, mb1=MB, mb2=MB) is None
          and forming_candidate(*_trunc(seq, 4), mb1=MB) is None)   # до пробоя-бара: отменён → None
    print("  G3 откат >50% → зонд None (как детектор):", g3); ok = ok and g3

    # G5: грязный толчок-1 (close внизу) → не толчок-1 ни у детектора, ни у зонда.
    seq = _mk([(100, 101.5, 100, 100.3), (100.3, 103, 100.2, 102.9)])
    sig = detect_v81(*seq, 2, mb1=MB, mb2=MB)
    g5 = ((sig is None or sig[0] != "long") and forming_candidate(*_trunc(seq, 3), mb1=MB) is None)
    print("  G5 грязный толчок-1 → зонд None:", g5); ok = ok and g5

    # C1: ЧИСТЫЙ forming — толчок-1 + консолидация БЕЗ пробоя → зонд ДАЁТ кандидата, детектор молчит (ядро ценности).
    seq = _mk([(100, 101.5, 100, 101.4), (101.4, 101.3, 100.9, 101.0)])
    cand = forming_candidate(*seq, mb1=MB)
    c1 = (detect_v81(*seq, 2, mb1=MB, mb2=MB) is None and cand is not None
          and cand["consolidation_bars"] == 1 and abs(cand["breakout_level"] - 101.5) < 1e-9)
    print("  C1 forming без пробоя → кандидат есть, сигнала нет:", c1); ok = ok and c1
    return ok


if __name__ == "__main__":
    print("ГЕЙТ ПАРИТЕТА зонд ↔ detect_v81:")
    print("OK" if gates() else "FAIL")
