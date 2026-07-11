# -*- coding: utf-8 -*-
"""strategy.scanner — живой сканер сигнала (Веха 5 ф.5.2 под-шаг 3b).

scan_signal воспроизводит РОЖДЕНИЕ сетапа движком run_v8 (v8_sim.py:105-115) причинно: на 4h-серии
от позиции курсора находит ПЕРВЫЙ родившийся сетап (бар-кандидат → пробой jc), отдаёт карточку +
номер бара-пробоя + следующий курсор детекции. ТОЛЬКО детекция/рождение — пере-якорь/цели/таймаут
ведёт lifecycle (под-шаг 4); постановку/гейты/триггер — app/cycle (под-шаг 3c).

Parity-закон: детектор/EMA/фибо — ДВИЖОК (detect_v81 + signal.signal_from_detect), не переписываем.
Зовём detect_v81 НАПРЯМУЮ (не find_signal): сканеру нужен jc даже при EMA-reject, чтобы двигать курсор
i=jc+1 ровно как run_v8 (find_signal прячет jc при отказе). Чистый модуль: без I/O/сети/БД; курсор — параметр.
"""
import numpy as np

import config
from strategy.engine.v81_sim import detect_v81
from strategy.signal import warm_ema, signal_from_detect


def scan_signal(o, h, l, c, t4, symbol, *, start_i=1,
                ema_enabled=None, shorts_enabled=None, stop_fib=None, mb1=None, mb2=None):
    """Первый РОДИВШИЙСЯ сетап на серии от индекса start_i, как сканировал бы run_v8.

    Возврат (sig, jc, next_i): карточка (signal_from_detect), бар-пробоя jc, следующий курсор детекции
    (jc+1). None — если до конца серии (n-1) сетап не родился. Курсор движется как движок (v8_sim.py:105-115):
      detect==None → i+=1;  short при only-long → i+=1;  EMA-reject → i=jc+1;  рождение → стоп, вернуть.
    ema_enabled/shorts_enabled/stop_fib — эффективные крутилки (None ⇒ дефолт config, как find_signal).

    ⚠ next_i = jc+1 — курсор ДЕТЕКЦИИ (искать СЛЕДУЮЩЕЕ рождение в ТОМ ЖЕ проходе). Это НЕ «курсор монеты
    после ведения»: движок после рождения прыгает i=k+1 (k=конец ведения ≫ jc, v8_sim.py:207-225) — в live
    этот сдвиг даёт lifecycle при ЗАКРЫТИИ сетапа (под-шаг 4). НЕ использовать next_i как «следующий сетап
    монеты» в торговом цикле без сдвига на k+1, иначе перекрытые сетапы. Гейт «один сетап на монету» — 3c.
    """
    if mb1 is None or mb2 is None:                         # боевой путь: гард + бары из конфига (БЕЗ изменений)
        cfg = config.strategy.COINS_CONFIG.get(symbol)
        if not cfg or not cfg.get("enabled"):
            return None                                    # неизвестная/выключенная монета — guard
        mb1, mb2 = cfg["mb1"], cfg["mb2"]
    # else (Веха 7): оба бара заданы явно (скаут) → гард пропущен, монета произвольная
    ema_on = ema_enabled if ema_enabled is not None else config.strategy.EMA_FILTER_ENABLED
    shorts = shorts_enabled if shorts_enabled is not None else config.strategy.SHORTS_ENABLED
    n = len(c)
    ema = warm_ema(c) if ema_on else None                  # тёплая EMA считаем РАЗ (не O(n²) на скан)

    i = max(int(start_i), 1)                               # detect_v81 требует i>=1
    while i < n - 1:
        imp = detect_v81(o, h, l, c, i, mb1, mb2,
                         retr=config.strategy.RETR, clean_thr=config.strategy.CLEAN_THR,
                         maxwin=config.strategy.MAXWIN)
        if imp is None:
            i += 1
            continue
        side, A, B, jc = imp
        if side != "long" and not shorts:                  # only-long-дроп (зеркало port_lib._longdet)
            i += 1
            continue
        if ema is not None and not np.isnan(ema[jc]):      # EMA-гейт на jc — дословно run_v8:112-115
            up = c[jc] > ema[jc]
            if (side == "long" and not up) or (side == "short" and up):
                i = jc + 1                                 # тренд враждебен → пропустить ВЕСЬ сетап (как движок)
                continue
        sig = signal_from_detect(side, A, B, jc, t4=t4, stop_fib=stop_fib)
        return sig, jc, jc + 1                             # рождение: карточка + бар-пробоя + след. курсор
    return None
