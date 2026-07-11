# -*- coding: utf-8 -*-
"""execution.lifecycle — событийная машина выходов V8.1 (Веха 3).

ЧИСТЫЙ решатель: on_fill / on_bar_close читают in-memory setup-карточку, продвигают состояние
и возвращают Action (что executor должен сделать с биржей). Сам ничего не шлёт, не тянет данные,
не пишет в БД (это executor / scheduler / state).

ГЛАВНЫЙ ЗАКОН — PARITY: решения == движок strategy/engine/v8_sim.run_v8. Геометрию ног считает
ДВИЖОК (pf.fib_price через lp/ext), правила выходов зеркалят run_v8 строка-в-строку (ссылки ниже).

on_fill — commit-латч + пересчёт целей/стопов открытых ног (после-commit каскад: shock / бегунок+БУ
/ нога3 / скальп) + завершение сетапа. on_bar_close — причинный пере-якорь до commit (REBUILD /
SKIP_FILLED) + beyond_B + timeout-72 по закрытым 4h-барам. Оба зеркалят run_v8 строка-в-строку.
"""
import config
from strategy.engine import pifagor_fib_backtest_v2_clean as pf

from .actions import (
    LV, PENDING, OPEN, CLOSED,
    none, close, rebuild, skip_filled, update_tp_sl, open_legs, reprice_entry,
)


def _profit(side, px, entry):
    """Направленный профит ноги (>0 = в плюс). long: px-entry; short: entry-px."""
    return (px - entry) if side == "long" else (entry - px)


def leg_targets(setup, *, runner_tp_hold=False, leg2_ext=None, trail_r=0.0):
    """Целевые (target, estop) для КАЖДОЙ открытой ноги — то, что должны кодировать стоящие
    reduce-only TP/SL. Пересчитывается каждое событие (shock/бегунок зависят от open_legs +
    profit_taken + beyond_B). Зеркалит run_v8 v8_sim.py:155-192. Возвращает {lv: (target, estop)}.

    Геометрия — движок: lp(L)=pf.fib_price(A,B,L,side), ext(m)=pf.fib_price(A,B,-m,side).

    runner_tp_hold (флаг RUNNER_TP_HOLD, LIVE-ONLY, ADR 0015): True ⇒ глубокой ноге-БЕГУНКУ в
    до-профитной не-shock фазе target=None (без резтинг-TP 0.236) — чинит живой разрыв, где два
    reduce-only TP на 0.236 бьют разом и гасят бегунок (движок берёт их ПО ОЧЕРЕДИ в баре). Дефолт
    False = поведение бит-в-бит. Движок НЕ трогаем.

    trail_r (крутилка TRAIL_R если TRAIL_ENABLED, LIVE-ONLY, путь Y/Дизайн A, R8): >0 ⇒ соло-бегунок за
    вершиной B ведём НАТИВНЫМ трейлером Bybit (ставит executor.maybe_arm_trailer). Здесь ЧИСТЫЙ решатель
    держит estop=stop0 (НЕ БУ ⇒ без миграции, вшитый Full = пол) и снимает фикс-цель ТОЛЬКО после
    подтверждённого арма (латч setup['trail_armed']). Дефолт 0.0 = поведение бит-в-бит. Движок НЕ трогаем.
    """
    side, A, B = setup["side"], setup["A"], setup["B"]
    lp = lambda L: float(pf.fib_price(A, B, L, side))
    ext = lambda m: float(pf.fib_price(A, B, -m, side))
    stop0 = setup["stop0"]
    opens = open_legs(setup)
    out = {}
    if not opens:
        return out

    if not setup["committed"]:
        # пре-commit: открыта только 0.382 -> защитный скальп 0.236 (v8_sim.py:158-160)
        for lv in opens:
            out[lv] = (lp(0.236), stop0)
        return out

    # ── POST-COMMIT каскад (v8_sim.py:171-192) ──
    profit_taken = setup["profit_taken"]
    shock = (not profit_taken) and (len(opens) == 3)
    deepest = max(opens)
    leg2_ext = leg2_ext if leg2_ext is not None else config.execution.LEG2_EXT   # эффективный (param воркёра) ← config-дефолт
    leg3_mode = config.execution.LEG3_MODE
    next_scalp = config.execution.NEXT_SCALP
    for lv in opens:
        ride = False
        if not profit_taken:
            T, estop = (lp(0.5) if shock else lp(0.236)), stop0          # 6a: до профита — скальп/shock
        elif lv == deepest and lv == 0.618:
            if leg3_mode == "ext":
                ride = True; T = ext(0.272)                               # 6b: нога3 ext-режим
            else:
                T, estop = lp(float(leg3_mode)), stop0                    # 6b: нога3 -> fib 0.382
        elif lv == deepest and lv == 0.5:
            if leg2_ext <= 0.0:
                T, estop = lp(0.0), stop0
            else:
                ride = True; T = ext(leg2_ext)                           # 6c: БЕГУНОК -> ext(1.0)=2.0R
        elif lv == deepest:
            T, estop = lp(0.236), stop0                                   # 6d: deepest fallback (0.382)
        else:
            T, estop = lp(next_scalp[lv]), stop0                          # 6e: не-deepest скальп
        if ride:
            estop = setup["legs"][lv]["entry"] if setup["beyond_B"] else stop0   # 6f: БУ за вершиной B
        out[lv] = (float(T), float(estop))
    # RUNNER_TP_HOLD (ADR 0015): держим глубокую ногу-БЕГУНОК без резтинг-TP 0.236 в до-профитной
    # не-shock фазе — НО только когда открыта и более мелкая нога (len(opens)>=2): та возьмёт 0.236
    # первой → profit_taken → каскад-retarget поднимет бегунок на ext. Иначе два reduce-only TP на
    # 0.236 бьют на бирже РАЗОМ и гасят бегунок (движок берёт их по очереди в баре). target=None ⇒
    # _desired_pool не ставит TP, нога держится вшитым Full-стопом. Подавляем ТОЛЬКО ride-роль
    # (deepest==0.5&LEG2_EXT>0 или deepest==0.618&LEG3_MODE=='ext'); скальп-роль И ОДИНОКУЮ ногу НЕ
    # трогаем — иначе движок-WIN (одинокая нога скальпит 0.236) стал бы live-LOSS (M1 аудита). Override
    # ПОСЛЕ float() ⇒ без float(None) (M4). flag-OFF ⇒ блок пропущен ⇒ бит-в-бит.
    if runner_tp_hold and not profit_taken and not shock and len(opens) >= 2:
        runner_leg = (deepest if ((deepest == 0.5 and leg2_ext > 0.0)
                                  or (deepest == 0.618 and leg3_mode == "ext")) else None)
        if runner_leg is not None and runner_leg in out:
            out[runner_leg] = (None, out[runner_leg][1])   # снять резтинг-TP бегунка, стоп сохраняем
    # TRAIL (R8, путь Y, Дизайн A): СОЛО-бегунок в ride-фазе ведём нативным трейлером Bybit (ставит executor).
    # Здесь: (a) estop=stop0 ВСЕГДА (НЕ БУ) → resting_stop не расходится → миграция НЕ триггерится → вшитый
    # Full = пол (is_covered через stopLoss>0, keystone-свип no-op); (b) фикс-цель снимаем ТОЛЬКО после
    # подтверждённого арма (trail_armed) — транзакц. «трейлер первым»: до арма держим baseline ext(leg2_ext).
    # Гейт not migrated: флаг-ON на уже-БУ-мигрированном бегунке НЕ трогаем — добьёт baseline, трейл со след.
    # сетапа (MAJOR-A аудита; в trail-mode бегунок и так НЕ мигрирует, так что гейт бьёт лишь мид-ride-флип).
    # trail_r<=0 И не armed ⇒ блок пропущен ⇒ бит-в-бит. Override ПОСЛЕ float() ⇒ без float(None).
    if (trail_r > 0.0 or setup.get("trail_armed")) and profit_taken and not shock \
            and len(opens) == 1 and not setup.get("migrated"):
        runner_leg = (deepest if ((deepest == 0.5 and leg2_ext > 0.0)
                                  or (deepest == 0.618 and leg3_mode == "ext")) else None)
        if runner_leg is not None and runner_leg in out:
            new_T = None if setup.get("trail_armed") else out[runner_leg][0]   # снять TP только после арма
            out[runner_leg] = (new_T, stop0)              # estop=stop0 (пол; без БУ/миграции)
    return out


def retarget(setup, *, runner_tp_hold=False, leg2_ext=None, trail_r=0.0):
    """Пересчитать стоящие TP/SL открытых ног и вернуть UPDATE_TP_SL по ИЗМЕНИВШИМСЯ
    (диф против leg['target']/leg['resting_stop']). Нет изменений -> NONE.
    resting_stop = ЭФФЕКТИВНЫЙ стоящий SL (stop0, либо entry=БУ для бегунка) — то, что реально
    стоит на бирже. РЕКОРД-стоп leg['istop'] (=stop0 при заливе) тут НЕ трогаем (parity записи).
    runner_tp_hold/leg2_ext/trail_r пробрасываются в leg_targets (ADR 0015; трейл — путь Y)."""
    targets = leg_targets(setup, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext, trail_r=trail_r)
    updates = []
    for lv, (T, estop) in targets.items():
        leg = setup["legs"][lv]
        if leg["target"] != T or leg["resting_stop"] != estop:
            leg["target"] = T
            leg["resting_stop"] = estop
            updates.append({"lv": lv, "target": T, "stop": estop})
    return update_tp_sl(updates) if updates else none()


def _is_complete(setup):
    """Сетап завершён (v8_sim.py:206/208): committed и (profit_taken+beyond_B+нет открытых)
    ИЛИ committed и все ноги закрыты."""
    legs = setup["legs"]
    no_open = not any(legs[lv]["state"] == OPEN for lv in LV)
    all_closed = all(legs[lv]["state"] == CLOSED for lv in LV)
    if setup["committed"] and setup["profit_taken"] and setup["beyond_B"] and no_open:
        return True
    if setup["committed"] and all_closed:
        return True
    return False


def _double_dip_reprice(setup, cond05, tol05):
    """Двойной заход: если 0.382 сняла скальп (leg1_scalped) и 0.5 ещё PENDING — Action пере-цены 0.5 на
    thr=lp(0.5)+tol*|B-A|; иначе None. OFF (cond05!='double_dip' или tol05<=0) → None (бит-в-бит).
    Grid-локальный: пере-якорь сбросил leg1_scalped → допуск снят.
    ⚠ База — СТАБИЛЬНАЯ фибо-цена (pf.fib_price), НЕ leg['entry']: последний перезаписывает write-ahead 2b,
    и если брать его — thr РАТЧЕТИТ вверх каждый бар (конвергентный re-emit) → слом паритета. Движок держит
    entries[0.5] стабильной до залива (v8_sim.py:147). После пере-цены дедуп (leg['entry']==thr) гасит re-emit."""
    if cond05 != "double_dip" or tol05 <= 0.0 or not setup.get("leg1_scalped"):
        return None
    leg = setup["legs"][0.5]
    if leg["state"] != PENDING:
        return None
    plain = float(pf.fib_price(setup["A"], setup["B"], 0.5, setup["side"]))   # СТАБИЛЬНАЯ база (не leg["entry"])
    thr = plain + tol05 * abs(setup["B"] - setup["A"])
    return reprice_entry(0.5, thr)


def on_fill(symbol, setup, fill_event, *, runner_tp_hold=False, leg2_ext=None, cond05=None, tol05=0.0, trail_r=0.0):
    """WS-событие залива/выхода -> Action. Мутирует setup на месте.

    fill_event: {kind:"entry"|"exit", lv:float, price:float, ebar?:int, link_id?}.
    entry: нога -> open (ebar/istop=stop0), commit-латч на 0.5 (v8_sim.py:153-154) -> retarget.
    exit:  нога -> closed; latch profit_taken если выход в плюс (v8_sim.py:202); completion -> CLOSE,
           иначе retarget оставшихся.
    runner_tp_hold/leg2_ext/trail_r -> retarget->leg_targets (ADR 0015; трейл путь Y; ОБА пути: commit-залив 0.5 и exit-каскад).
    """
    lv = fill_event["lv"]
    if lv not in setup["legs"]:
        return none()
    leg = setup["legs"][lv]
    kind = fill_event["kind"]

    if kind == "entry":
        if leg["state"] != PENDING:
            return none()                                # идемпотентность: уже залита
        leg["state"] = OPEN
        leg["filled"] = True
        leg["ebar"] = fill_event.get("ebar", leg["ebar"])   # 4h-индекс залива
        leg["istop"] = setup["stop0"]                    # РЕКОРД-стоп фиксирован при заливе (v8_sim.py:143), не меняется
        leg["resting_stop"] = setup["stop0"]             # стартовый стоящий SL (двинется в БУ через retarget)
        if leg["link_id"] is None:
            leg["link_id"] = fill_event.get("link_id")
        if lv == config.execution.COMMIT_LV and not setup["committed"]:
            setup["committed"] = True                    # commit ЕСТЬ залив 0.5 (v8_sim.py:153-154)
            setup["wait_postcommit"] = 0
        return retarget(setup, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext, trail_r=trail_r)

    if kind == "exit":
        if leg["state"] != OPEN:
            return none()                                # идемпотентность: уже закрыта/не открыта
        leg["state"] = CLOSED
        if _profit(setup["side"], float(fill_event["price"]), leg["entry"]) > 0:
            setup["profit_taken"] = True                 # latch на плюсовом выходе (v8_sim.py:202)
            if lv == 0.382 and not setup["committed"]:
                setup["leg1_scalped"] = True             # двойной заход: 0.382 сняла скальп пре-коммит (v8_sim.py:191-192)
        if _is_complete(setup):
            still_open = [l for l in LV if setup["legs"][l]["state"] == OPEN]
            return close(still_open, "complete")
        rp = _double_dip_reprice(setup, cond05, tol05)   # двойной заход: пере-цена 0.5, если латч взведён (первичный emit)
        if rp is not None:
            return rp
        return retarget(setup, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext, trail_r=trail_r)

    return none()


def _reanchor(setup, new_B):
    """Причинный пере-якорь до commit (v8_sim.py:147-149): B -> новый экстремум, перерисовать
    entries/stop0 движком, сбросить profit_taken/beyond_B. ВСЕ ноги -> PENDING (ре-арм закрытой
    скальп-ноги для v3; no-op при v2-заморозке, где все и так pending) + очистка live-полей —
    зеркалит движок (state={pending}; ebar={}; istop={}, v8_sim.py). Гейт on_bar_close гарантирует
    НЕТ открытых ног, поэтому сброс в PENDING безопасен (open-ногу не обнулим)."""
    side = setup["side"]
    setup["B"] = float(new_B)
    lp = lambda L: float(pf.fib_price(setup["A"], setup["B"], L, side))
    for lv in LV:
        leg = setup["legs"][lv]
        was_closed = leg["state"] == CLOSED          # ре-армим ТОЛЬКО закрытую скальп-ногу (v3)
        leg["state"] = PENDING                       # no-op если уже pending (v2)
        leg["entry"] = lp(lv)
        leg["target"] = None; leg["resting_stop"] = None
        if was_closed:                               # очистить fill-поля ре-армленной ноги → свежий ордер в place_setup.
            leg["filled"] = False                    # link_id/order_id/qty ОСТАВШИХСЯ PENDING-ног НЕ трогаем —
            leg["ebar"] = None; leg["istop"] = None  # иначе cancel_all_legs пропустит снятие старых resting-лимиток (v2 регресс).
            leg["order_id"] = None; leg["link_id"] = None; leg["qty"] = None
    setup["stop0"] = lp(setup.get("stop_fib", config.execution.STOP_FIB))   # карточкин stop_fib (единый с сигналом); fallback — старые карточки без поля
    setup["profit_taken"] = False
    setup["beyond_B"] = False
    setup["leg1_scalped"] = False                # двойной заход: пере-якорь снимает допуск (живое зеркало v8_sim.py:171)


def on_bar_close(symbol, setup, bar, reanchor_after_scalp=False, *, runner_tp_hold=False, leg2_ext=None,
                 cond05=None, tol05=0.0, trail_r=0.0):
    """Закрытие 15m-бара -> Action. bar = {high, low, is_4h_close?} (just-closed 15m-бар;
    high/low — python float; is_4h_close опционален, дефолт False -> timeout считается только на 4h).

    Причинный пере-якорь до commit (только если ВСЕ ноги pending; v8_sim.py:145-150) -> REBUILD;
    если новый экстремум, но нога уже залита -> SKIP_FILLED (якорь заморожен, инвариант #9).
    beyond_B по новому экстремуму (151-152). timeout: wait_postcommit++ ТОЛЬКО на 4h-границе
    (212-214), CLOSE при TIMEOUT_BARS=72. Заливы/выходы — не здесь (это on_fill).
    """
    side = setup["side"]
    hi, lo = bar["high"], bar["low"]
    legs = setup["legs"]
    new_extreme = (hi > setup["B"]) if side == "long" else (lo < setup["B"])

    # ── ПРЕ-COMMIT: причинный пере-якорь / заморозка (v2) или перезарядка после скальпа (v3) ──
    if not setup["committed"]:
        if new_extreme:
            no_open = not any(legs[lv]["state"] == OPEN for lv in LV)
            has_closed = any(legs[lv]["state"] == CLOSED for lv in LV)
            # Мирроринг движка (_allow, v8_sim.py): all-pending -> пере-якорь; закрытая скальп-нога
            # -> пере-якорь ТОЛЬКО при v3 (reanchor_after_scalp); иначе заморозка (инвариант #9).
            # no_open == движковый «not filled_this»: нога, залитая в ЭТОМ баре, на on_bar_close ещё OPEN.
            if not no_open:
                _allow = False
            elif not has_closed:
                _allow = True                         # all-pending (v2 и v3)
            elif reanchor_after_scalp == "win":
                _allow = setup["profit_taken"]        # v3-win: только после плюсового скальпа
            elif reanchor_after_scalp:
                _allow = True                         # v3: после любого закрытого скальпа
            else:
                _allow = False                        # v2: закрытая нога замораживает якорь
            if _allow:
                _reanchor(setup, hi if side == "long" else lo)   # сбрасывает leg1_scalped → допуск снят
                return rebuild(setup)
            setup["beyond_B"] = True                  # залив/заморозка якоря
            # НЕ пере-якорь (заморозка) → падаем в конвергентную пере-цену double-dip ниже
        rp = _double_dip_reprice(setup, cond05, tol05)   # конвергентный re-emit (ретрай, если первичный amend не сел)
        if rp is not None:
            return rp
        if new_extreme:
            return skip_filled()                      # заморозка без double-dip
        return none()                                 # ждём заливов

    # ── POST-COMMIT: beyond_B / timeout / ретаргет БУ ──
    if new_extreme:
        setup["beyond_B"] = True
    if bar.get("is_4h_close"):                        # timeout считает ЗАКРЫТЫЕ 4h-бары (не 15m!)
        setup["wait_postcommit"] += 1
        if setup["wait_postcommit"] >= config.execution.TIMEOUT_BARS:
            still_open = [lv for lv in LV if legs[lv]["state"] == OPEN]
            return close(still_open, "timeout")
    return retarget(setup, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext, trail_r=trail_r)            # beyond_B мог сдвинуть БУ-стоп бегунка
