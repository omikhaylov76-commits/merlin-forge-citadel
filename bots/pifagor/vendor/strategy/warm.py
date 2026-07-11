# -*- coding: utf-8 -*-
"""strategy.warm — ядро детекции ТЁПЛОГО СТАРТА (Веха 5.8, под-шаг 1).

Чистый модуль (БЕЗ ордеров/сети/БД/состояния): на свежей 4h-серии + эффективных крутилках
классифицирует ТЕКУЩИЙ живой сетап монеты как PENDING / OPEN (или None = нет кандидата),
ЧЕСТНО прогоняя ТЕ ЖЕ движок+lifecycle до последнего закрытого 4h-бара. Ничего не выдумываем.

ЗАКОН ПАРИТЕТА (переиспользуем, НЕ переписываем):
  • РОЖДЕНИЕ сетапа — `scanner.scan_signal` (detect_v81 + EMA + фибо движка), тот же, что торговый цикл;
  • ВЕДЕНИЕ до текущего бара — ЖИВАЯ машина `execution.lifecycle` (on_fill/on_bar_close), событие-за-
    событием, как приёмочный harness tests/test_lifecycle_parity._live_records (симуляция биржи —
    тач-тест стоящих лимиток/reduce-only), но КАЖДЫЙ 4h-бар = один суб-бар.

РАЗРЕШЕНИЕ 4h (осознанно): снимок «как на закрытии последнего 4h», каждый 4h-бар = один суб-бар.
Внутрибарный дрейф несущественен для ГЕОМЕТРИИ ног, но для КЛАССА (pending/open) 4h≠15m в одном случае —
пре-commit ПЕРЕ-ЯКОРЬ: 4h видит «новый хай + откат» как ОДИН бар и решает «залив → якорь» в фикс. порядке,
а 15m мог переставить «новый хай → якорь ВВЕРХ → залив уже по НОВОЙ сетке». Тогда 4h-PENDING может
расходиться с 15m (аудит 5.8 это falsified — наивная «PENDING всегда консервативен» НЕВЕРНА под пере-якорем).
ПОЭТОМУ безопасность авто-пути опирается на ФЛАГ auto_eligible, а НЕ на класс:
  • «4h [low,high] ⊇ 15m ⟹ не коснулись ⟹ 15m тоже pending» — строго верно ТОЛЬКО для НЕСДВИНУТОЙ сетки
    (без пере-якоря за прогон). Такой PENDING — auto_eligible=True (авто-годен, честный паритет).
  • PENDING С пере-якорем за прогон — auto_eligible=False: сетка сдвигалась, класс может расходиться с 15m →
    ТОЛЬКО КНОПКА (человек глазами), не авто.
  • OPEN — «вход по рынку ≈» (кнопка): цена/класс приблизительны (4h может дать ложный OPEN там, где 15m
    уже вышел — оператор подтверждает). Никогда не авто (auto_eligible=False).

Кандидат = сетап, который движок, доведённый до текущего бара, ВСЁ ЕЩЁ держал бы активным, и чей
ПРОБОЙ в пределах окна (max_age_bars закрытых 4h; дефолт TIMEOUT_BARS). Три исхода:
  • PENDING — ВСЕ 3 ноги ещё стоят лимитами. auto_eligible ⟺ не было пере-якоря за прогон (иначе кнопка).
  • OPEN    — ≥1 нога залита (движок В ПОЗИЦИИ сейчас). Вход по рынку ≈. Только кнопка (auto_eligible=False).
  • None    — сетап закрыт (стоп/таймаут/профит) ЛИБО частично отработан без открытой ноги (мелкая
              нога закрылась, глубокие ещё ждут — НЕ чистый кандидат) ЛИБО нет живого пробоя в окне.

ПОЧЕМУ ОКОННО, А НЕ С НАЧАЛА СЕРИИ (важно — эмпирически проверено): 4h-разрешение расходится с 15m-движком
на длинном горизонте. Пре-commit сетап, чья мелкая нога залилась-и-скальпнула, на 4h «застревает»
(не пере-якорится — не все ноги pending; не коммитится — 0.5 не залита; таймаута нет — он пост-commit),
тогда как 15m-движок идёт дальше и рождает новые сетапы. Замер: сплошной 4h-прогон с начала застревает
на ~⅓ серии (BTC на баре 6952 из 19366), а движок торгует до бара 19041 — прогон с начала МИССИТ все
недавние сетапы. Поэтому: (1) ДЕТЕКЦИЯ пробоев — оконная (последние ~2×max_age баров; детект чист, не
застревает; сам пробой не зависит от лайфцикла); (2) КАЖДЫЙ пробой в окне прогоняем ИЗОЛИРОВАННО от его
jc до n-1 (дивергенция ограничена ≤ окна, застрявший/частичный просто отбрасывается); (3) берём САМЫЙ
СВЕЖИЙ реально-активный (freshest — релевантнее для подхвата и безопаснее «древнего» committed). Один
кандидат на монету (= гейт «один сетап на монету»). ЧЕСТНО: детекция ОККУПАНТНОСТЬ-АГНОСТИЧНА — движок
после ведения сетапа прыгает i=k+1 (k≫jc), ПРОПУСКАЯ пробои внутри чужого лайфцикла, а мы их собираем;
поэтому «самый свежий активный» — ПРОКСИ, а не точная копия «что держит движок» (аудит 5.8: совпадение
~неполное). Смягчается тремя слоями ПЕРЕД постановкой (поздние под-шаги): (а) авто берёт только
auto_eligible (нетронутый PENDING); (б) reconcile (5.7) + has_active сверяют реальную позицию на бирже;
(в) человек-галочка на OPEN/кнопке. Demo-режим обучения — не боевой.
"""
import config
from strategy.scanner import scan_signal
from strategy.signal import signal_from_detect
from execution import lifecycle as LC
from execution.actions import (
    setup_from_signal, LV, open_legs,
    PENDING as LEG_PENDING, REBUILD, CLOSE,
)

# Метки класса кандидата (не путать с фазами НОГИ LEG_PENDING/LEG_OPEN из actions).
PENDING = "PENDING"
OPEN = "OPEN"


def _replay_setup_4h(setup, h4, l4, jc, n):
    """Прогнать ОДИН сетап от бара jc+1 до конца серии на 4h-разрешении ЖИВОЙ машиной lifecycle.

    Зеркалит tests/test_lifecycle_parity._live_records (порядок: заливы → пере-якорь/beyond_B →
    выходы стоп-раньше-цели → завершение → timeout на закрытом 4h), но каждый 4h-бар = один суб-бар
    (h4[k], l4[k]). Мутирует setup на месте — его финальное состояние есть снимок «на текущем баре».
    Возврат: (closed_at, reanchored). closed_at — индекс бара ЗАКРЫТИЯ, либо None если дошёл до конца
    активным (in-flight). reanchored — был ли ХОТЬ ОДИН пре-commit пере-якорь за прогон (REBUILD): при
    сдвиге сетки 4h-класс может расходиться с 15m → снимает auto_eligible (см. §РАЗРЕШЕНИЕ 4h в шапке).
    """
    side = setup["side"]
    reanchored = False
    k = jc + 1
    while k < n:
        hh, ll = float(h4[k]), float(l4[k])
        # 1. БИРЖА: заливы лимиток (v8_sim.py:141-143) — pending-нога, цена в её зоне [ll,hh]
        filled_this = []
        for lv in LV:
            leg = setup["legs"][lv]
            if leg["state"] == LEG_PENDING and ll <= leg["entry"] <= hh:
                LC.on_fill("W", setup, {"kind": "entry", "lv": lv, "ebar": k})
                filled_this.append(lv)
        # 2. БОТ: причинный пере-якорь / beyond_B / ретаргет (v8_sim.py:145-152; НЕ timeout)
        act = LC.on_bar_close("W", setup, {"high": hh, "low": ll, "is_4h_close": False})
        if act.kind == REBUILD:                       # пере-якорь → новая сетка, пропустить остаток бара
            reanchored = True                         # сетка сдвигалась → PENDING не auto_eligible
            k += 1
            continue
        # 3. БИРЖА: выходы по стоящим reduce-only TP/SL (v8_sim.py:155-205; стоп РАНЬШЕ цели).
        #    Снимок целей/стопов берём ОДИН раз на бар (движок считает их раз с фикс. open_legs).
        snap = {lv: (setup["legs"][lv]["target"], setup["legs"][lv]["resting_stop"])
                for lv in open_legs(setup)}
        for lv in LV:
            if lv not in snap:
                continue
            T, estop = snap[lv]
            if estop is None:
                continue
            sh = (ll <= estop) if side == "long" else (hh >= estop)
            th = (T is not None) and ((hh >= T) if side == "long" else (ll <= T)) \
                and (lv not in filled_this)           # no_same_subbar_tp (v8_sim.py:165/200)
            if sh:
                LC.on_fill("W", setup, {"kind": "exit", "lv": lv, "price": estop})
            elif th:
                LC.on_fill("W", setup, {"kind": "exit", "lv": lv, "price": T})
        # 4. завершение сетапа (v8_sim.py:206-208)
        if LC._is_complete(setup):
            return k, reanchored
        # 5. timeout — на ЗАКРЫТОМ 4h-баре (v8_sim.py:212-218): здесь каждый бар и есть закрытый 4h
        act = LC.on_bar_close("W", setup, {"high": hh, "low": ll, "is_4h_close": True})
        if act.kind == CLOSE and act.payload.get("reason") == "timeout":
            return k, reanchored
        k += 1
    return None, reanchored                            # дошли до конца серии активным (in-flight)


def _descriptor(symbol, setup, jc, t4, price_now, age_bars, reanchored):
    """Собрать дескриптор кандидата из ТЕКУЩЕЙ (возможно пере-якоренной) карточки setup.

    kind: OPEN если есть открытая нога, иначе PENDING (звать только для чистого кандидата — см. classify).
    entries/stop — движок `signal_from_detect` на ТЕКУЩИХ (A,B) карточки (= сетка, что поставил бы свежий
    сетап; для PENDING — точная постановка). t4 — опц. массив open-time (bar_time пробоя).

    auto_eligible = PENDING И не было пере-якоря за прогон — ТОЛЬКО такой сетап авто-годен (без сдвига сетки
    аргумент «4h⊇15m» строг; см. §РАЗРЕШЕНИЕ 4h). OPEN и пере-якоренный PENDING → False (только кнопка).

    targets/est_risk_pct различны по классу (аудит 5.8):
      • PENDING — targets НАЧАЛЬНЫЕ (движок на сетке), est_risk от лимит-входа мелкой ноги (реальный сайзинг —
        кладём эти лимитки);
      • OPEN — targets БЕГУЩИЕ (lifecycle.leg_targets открытых ног, а не начальные — иначе завышаем апсайд),
        est_risk от РЫНОЧНОЙ цены price_now (вход по рынку, а не по лимиту).
    est_risk_pct — геометрический прокси в %, ДО сайзинга по капиталу (сайзинг — на вызывающем).
    """
    opens = open_legs(setup)
    kind = OPEN if opens else PENDING
    canon = signal_from_detect(setup["side"], setup["A"], setup["B"], int(jc),
                               t4=t4, stop_fib=setup.get("stop_fib"))
    entries, stop = canon["entries"], canon["stop"]
    if opens:
        targets = {lv: T for lv, (T, _estop) in LC.leg_targets(setup).items()}   # БЕГУЩИЕ цели открытых ног
        est_risk_pct = abs(price_now - stop) / price_now * 100.0 if price_now else None  # вход по рынку
    else:
        targets = canon["targets"]                                               # НАЧАЛЬНЫЕ (постановка лимиток)
        shallow = entries[LV[0]]                                                  # 0.382 — самая мелкая (ближняя к B)
        est_risk_pct = abs(shallow - stop) / shallow * 100.0 if shallow else None
    auto_eligible = (kind == PENDING) and (not reanchored)
    if opens:
        note = "уже в позиции (открыто ног: %d) — вход по рынку ≈" % len(opens)
    elif reanchored:
        note = "ноги стоят лимитами, НО сетка сдвигалась (пере-якорь) — только кнопка, проверь глазами"
    else:
        note = "ноги стоят лимитами, сетка нетронута (пробой %d бар(ов) назад) — авто-годен" % age_bars
    return {
        "symbol": symbol,
        "kind": kind,
        "auto_eligible": bool(auto_eligible),
        "reanchored": bool(reanchored),
        "side": setup["side"],
        # Сырые якоря движка (для build_setup → parity-постановка; entries/stop — производные от них).
        "A": float(setup["A"]),
        "B": float(setup["B"]),
        "stop_fib": setup.get("stop_fib"),
        "breakout_time": canon.get("bar_time"),
        "breakout_bar": int(jc),
        "age_bars": int(age_bars),
        "entries": entries,
        "stop": stop,
        "targets": targets,
        "price_now": float(price_now),
        "est_risk_pct": est_risk_pct,
        "note": note,
    }


def build_setup(desc):
    """Карта ведомого сетапа из дескриптора — для ПОСТАНОВКИ при авто-подхвате (warm_start_auto).

    Та же точка геометрии движка (signal_from_detect → setup_from_signal), что и свежий сетап торгового
    цикла: для auto_eligible PENDING карта БАЙТ-в-БАЙТ совпадает со свежей (A/B/jc/stop_fib несдвинуты —
    аудит 5.8: 0 дрейфа). bar_time докладываем из дескриптора (signal_from_detect без t4 → иначе NULL в
    мониторе). «Глупый» ре-конструктор: доверяет дескриптору, фильтры (EMA/shorts) уже прошли при рождении,
    None вернуть не может. ⚠ Для OPEN/пере-якоренного (под-шаг 5) — это карта-СЕТКА по текущим A/B, НЕ
    рыночная заявка входа; не исполнять как OPEN-вход по рынку."""
    sig = signal_from_detect(desc["side"], desc["A"], desc["B"], int(desc["breakout_bar"]),
                             stop_fib=desc.get("stop_fib"))
    setup = setup_from_signal(sig)
    setup["bar_time"] = desc.get("breakout_time")
    return setup


def _window_breakouts(o, h, l, c, t4, symbol, w0, n, kn):
    """Все пробои с jc в окне [w0, n-2] — детект-курсором сканера (как tests/test_scanner parity-цикл).

    Детекция чиста (не застревает в лайфцикле). Скан начинаем РАНЬШЕ w0 (на ~max_age) — толчок-2 (jc) в
    окне может иметь бар1 до w0; фильтруем результат по jc>=w0. Возврат: [(jc, sig)] по возрастанию jc.
    """
    max_age = kn["max_age"]
    scan_from = max(1, w0 - max_age)                  # запас на длину консолидации (jc-бар1); реально ≪ max_age
    out = []
    start_i = scan_from
    while start_i < n - 1:
        res = scan_signal(o, h, l, c, t4, symbol, start_i=start_i,
                          ema_enabled=kn["ema"], shorts_enabled=kn["shorts"], stop_fib=kn["stop_fib"])
        if res is None:
            break
        sig, jc, next_i = res
        if jc >= w0:                                  # пробой в окне свежести (age = n-1-jc <= max_age)
            out.append((jc, sig))
        start_i = next_i                              # детект-курсор = jc+1: собрать ВСЕ пробои (оккупантность-агностично)
    return out


def classify(o, h, l, c, t4, symbol, *, ema_enabled=None, shorts_enabled=None,
             stop_fib=None, max_age_bars=None):
    """Классифицировать ТЕКУЩИЙ живой сетап монеты по 4h-серии → дескриптор кандидата или None.

    o,h,l,c — закрытые 4h-бары (numpy, как в app/cycle._to_arrays); t4 — open-time (сек) или None.
    ema_enabled/shorts_enabled/stop_fib — эффективные крутилки (None ⇒ дефолт config, как find_signal/scanner).
    max_age_bars — окно «свежести пробоя» (None ⇒ config.execution.TIMEOUT_BARS). Возврат:
      • dict-дескриптор (PENDING/OPEN, + флаг auto_eligible) — САМЫЙ СВЕЖИЙ активный пробой в окне;
      • None — нет активного пробоя в окне (все закрыты / частичны без открытой ноги / нет пробоя / неизвестна монета).

    Оконная детекция + изолированный прогон каждого пробоя (см. §ПОЧЕМУ ОКОННО в шапке модуля).
    """
    cfg = config.strategy.COINS_CONFIG.get(symbol)
    if not cfg or not cfg.get("enabled"):
        return None                                   # неизвестная/выключенная монета — guard (= сканер)
    n = len(c)
    if n < 2:
        return None
    max_age = int(max_age_bars) if max_age_bars is not None else config.execution.TIMEOUT_BARS
    w0 = max(1, (n - 1) - max_age)                    # старт окна свежести (jc>=w0 ⟺ age<=max_age)
    kn = {"ema": ema_enabled, "shorts": shorts_enabled, "stop_fib": stop_fib, "max_age": max_age}

    breakouts = _window_breakouts(o, h, l, c, t4, symbol, w0, n, kn)
    for jc, sig in reversed(breakouts):               # САМЫЙ СВЕЖИЙ первым: freshest active wins
        setup = setup_from_signal(sig)
        closed_at, reanchored = _replay_setup_4h(setup, h, l, jc, n)
        if closed_at is not None:
            continue                                  # закрылся до текущего бара → не активен
        opens = open_legs(setup)
        pendings_all = all(setup["legs"][lv]["state"] == LEG_PENDING for lv in LV)
        if not opens and not pendings_all:
            continue                                  # частично отработан без открытой ноги — не чистый кандидат
        return _descriptor(symbol, setup, jc, t4, c[n - 1], (n - 1) - jc, reanchored)
    return None
