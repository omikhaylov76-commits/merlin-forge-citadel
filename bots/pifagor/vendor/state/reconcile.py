# -*- coding: utf-8 -*-
"""state.reconcile — сверка фаз сетапа с биржей при старте (ADR 0008, «биржа = арбитр»).

При рестарте (Railway-редеплой/сбой) снимок БД мог разойтись с фактом на бирже. one-way (ADR 0007):
биржа даёт ОДИН нетто-размер + пул reduce-only условных; пер-ножные позиции не видны. Поэтому:
- доказуемо биржей: какие -ent лимитки ещё стоят (match по link_id), общий нетто-размер, наличие
  пуловых -stp (миграция). Снимок даёт НЕвыводимое (beyond_B/profit_taken/migrated/wait_*).
- расхождение -> правим к бирже (нетто — арбитр ИТОГА). Пер-ножное разложение нетто через историю
  исполнений — backlog (D3); здесь: доверяем партиции снимка + жадно привязываем неучтённый нетто к
  PENDING-ногам с исчезнувшей -ent (мелкая→глубокая — порядок залива лонга).

ЧИСТАЯ reconcile_setup (без IO) + тонкий оркестратор reconcile_on_start (читает брокера, пишет store).
Проводку на старте делает интеграция (Веха 5); kill-switch до постановки — там же.
"""
from execution.actions import PENDING, OPEN, CLOSED
from logging_.trade_logger import get_logger

_QTY_TOL = 1e-9


def reconcile_setup(symbol, snapshot, net_position, live_orders):
    """Свести снимок карточки с фактом биржи. Возвращает (corrected_setup|None, action):
      action ∈ {'none' (нет снимка), 'exited' (вышел/мёртв -> чистить), 'kept' (поправлен, сохранить)}.
    net_position: {'size': float, ...} | None (one-way нетто-лонг). live_orders: список dict ордеров
    биржи (стоящие -ent лимитки + пул -tgt/-stp), match по orderLinkId."""
    if snapshot is None:
        return None, "none"
    net = float(net_position["size"]) if net_position else 0.0
    links = {o.get("orderLinkId") for o in live_orders if o.get("orderLinkId")}
    resting_ent = {l for l in links if l.endswith("-ent")}
    has_pool_stp = any(l.endswith("-stp") for l in links)

    # committed и позиция плоская -> весь сетап вышел в простое
    if snapshot.get("committed") and net == 0.0:
        return None, "exited"

    # миграция Full->пул выведена из наличия пуловых -stp на бирже
    if not snapshot.get("migrated") and has_pool_stp:
        snapshot["migrated"] = True

    legs = snapshot.get("legs", {})
    open_qty = sum((legs[lv].get("qty") or 0.0) for lv in legs if legs[lv].get("state") == OPEN)
    unaccounted = net - open_qty

    # PENDING-ноги с исчезнувшей -ent: залились в простое (если неучтённый нетто покрывает) или отменены.
    for lv in sorted(legs):                       # мелкая->глубокая: порядок залива лонга
        leg = legs[lv]
        if leg.get("state") != PENDING:
            continue
        link = leg.get("link_id")
        if link and link in resting_ent:
            continue                              # лимитка ещё стоит -> pending ок
        q = leg.get("qty") or 0.0
        if q > 0 and unaccounted >= q - _QTY_TOL:
            leg["state"] = OPEN                   # залилась в простое (нетто вырос на её объём) — НЕ теряем позицию
            leg["filled"] = True
            unaccounted -= q
        else:
            leg["state"] = CLOSED                 # -ent снята, нетто не вырос -> отменена (stale-leg, V7)

    # после сверки: ни одной открытой/стоящей ноги -> мёртвый сетап (всё отменено/закрыто), чистим
    if not any(leg.get("state") in (OPEN, PENDING) for leg in legs.values()):
        return None, "exited"
    return snapshot, "kept"


def read_resting_orders(broker, symbol, prefix):
    """Снимок НАШИХ стоящих ордеров символа с биржи (per-tick poll, под-шаг 4a):
      {"ent": set(linkId стоящих -ent лимиток), "pool": {linkId -tgt/-stp: triggerPrice}}.
    Union лимиток и условных (-tgt/-stp видны только с orderFilter='StopOrder') — тот же паттерн, что
    reconcile_on_start. Фильтр по нашему префиксу (чужие ордера на счёте игнорируем). Брокер raise →
    пробрасываем (тик пропустится в _poll_tick по этой монете; биржа=арбитр на следующем тике)."""
    pfx = f"{prefix}-{symbol}-"
    ent, pool = set(), {}
    for o in broker.get_open_orders(symbol):                       # активные лимитки (-ent)
        link = o.get("orderLinkId")
        if link and link.startswith(pfx) and link.endswith("-ent"):
            ent.add(link)
    for o in broker.get_open_orders(symbol, order_filter="StopOrder"):   # условные (-tgt/-stp)
        link = o.get("orderLinkId")
        if link and link.startswith(pfx) and (link.endswith("-tgt") or link.endswith("-stp")):
            pool[link] = o.get("triggerPrice")
    return {"ent": ent, "pool": pool}


def diff_setup_vs_exchange(setup, live_ent, live_pool, net, link_of, *, tol=_QTY_TOL):
    """ЧИСТО: свести карточку сетапа с фактом биржи (poll-diff, под-шаг 4a) и вернуть (entries, exits) —
    переходы для прогона через lifecycle.on_fill. БАЗА = САМА КАРТОЧКА (что ДОЛЖНО стоять), не prev-тик —
    рестарт-безопасно, закрытая нога сама уходит из ожидаемого (идемпотентность).
      live_ent : set стоящих -ent линков; live_pool: set стоящих -tgt/-stp линков; net: нетто-размер.
      link_of(lv, role) -> ожидаемый orderLinkId (executor._link). Геометрия движка НЕ трогается.

    entries = [lv, ...]                  PENDING-ноги, чья -ent исчезла И нетто покрывает (залив);
                                         жадно мелкая→глубокая, ограничено неучтённым нетто (как reconcile_setup).
    exits   = [(lv, role, price, exit_link), ...]  OPEN-ноги, чей ожидаемый выходной линк исчез (role
                                         'target'/'stop', ограничено падением нетто) ИЛИ полный флэт (net≈0 →
                                         embedded-Full стоп → ВСЕ открытые как 'stop'). price — с КАРТЫ (знак
                                         profit_taken). exit_link (ws_stage_b_preconditions) — orderLinkId, под
                                         которым придёт WS-исполнение выхода: пул -tgt/-stp (rule A) или ВХОДНОЙ
                                         -ent (rule B embedded); для офлайн-сверки края Стадии B."""
    legs = setup["legs"]
    open_lvs = [lv for lv in sorted(legs) if legs[lv].get("state") == OPEN]
    open_qty = sum((legs[lv].get("qty") or 0.0) for lv in open_lvs)
    unaccounted = net - open_qty

    entries = []
    if unaccounted > tol:                                          # нетто ВЫШЕ открытых ног → PENDING залились
        for lv in sorted(legs):                                   # мелкая→глубокая: порядок залива лонга
            leg = legs[lv]
            if leg.get("state") != PENDING:
                continue
            if leg.get("link_id") and leg["link_id"] in live_ent:  # лимитка ещё стоит → не залита
                continue
            q = leg.get("qty") or 0.0
            if q > 0 and unaccounted >= q - tol:
                entries.append(lv)
                unaccounted -= q

    exits = []
    if unaccounted < -tol:                                        # нетто НИЖЕ открытых ног → выходы
        drop = -unaccounted
        for lv in open_lvs:                                       # rule A: исчезнувшие выходные линки (мелкая→глубокая)
            leg = legs[lv]
            tgt_gone = leg.get("target") is not None and link_of(lv, "tgt") not in live_pool
            stp_gone = (setup.get("migrated") and leg.get("resting_stop") is not None
                        and link_of(lv, "stp") not in live_pool)
            if not (tgt_gone or stp_gone):
                continue
            q = leg.get("qty") or 0.0
            if q <= 0 or drop < q - tol:                          # падение нетто ещё не покрыло ногу → перенос на след. тик
                continue
            if stp_gone:                                          # коллизия tgt+stp одной ноги → СТОП (stop-before-target)
                exits.append((lv, "stop", leg.get("resting_stop"), link_of(lv, "stp")))    # rule A: пул-стоп
            else:
                exits.append((lv, "target", leg.get("target"), link_of(lv, "tgt")))         # rule A: пул-таргет
            drop -= q

    if net <= tol:                          # rule B: полный флэт (embedded-Full стоп без линка) → закрыть ВСЕ открытые
        done = {e[0] for e in exits}
        for lv in open_lvs:
            if lv not in done:
                # rule B: стоп ВШИТ в ВХОДНОЙ ордер (пул-линка нет) → exit_link = ВХОДНОЙ link_id (WS-исполнение
                # выхода придёт под ним; эмпирически подтвердить — под-шаг 8). См. ws_stage_b_preconditions.
                exits.append((lv, "stop", legs[lv].get("resting_stop"), legs[lv].get("link_id")))

    exits.sort(key=lambda e: e[0])                                # детерминизм: мелкая→глубокая (каскад completion)
    return entries, exits


def reconcile_on_start(store, broker, symbols, logger=None):
    """ОДИН раз на старте (до первого тика): по каждому символу свести снимок store с биржей и
    поправить/очистить state. Возвращает сводку {symbol: action}. Логирует решения и дивергенции
    (наблюдаемость demo-форварда; reconcile_setup остаётся ЧИСТОЙ). Вызывает интеграция (Веха 5)."""
    log = logger or get_logger("pifagor.reconcile")
    positions = {p.get("symbol"): p for p in broker.get_positions()}
    for p in positions.values():              # one-way long-only: SHORT на счёте — аномалия (ADR 0001/0007)
        if p.get("side") not in ("Buy", None):
            log.warning("reconcile: НЕ-лонг позиция %s side=%s size=%s — one-way long-only нарушен?",
                        p.get("symbol"), p.get("side"), p.get("size"))
    summary = {}
    for symbol in symbols:
        snapshot = store.get(symbol)
        if snapshot is None:
            net_pos = positions.get(symbol)                       # 5.7 п.3: позиция БЕЗ карточки = СИРОТА (сверка всего счёта)
            if net_pos and float(net_pos.get("size") or 0) > _QTY_TOL:
                sl = float(net_pos.get("stop_loss") or 0)         # 5.7 граница фазы: ЧЕСТНО сверить вшитый Full-стоп (0=нет);
                naked = sl <= 0                                    # свип покрытия (keystone-1) сироту НЕ армирует (нет карточки) → не врём «защищена»
                if naked:                                         # ГОЛАЯ сирота — стопа на бирже НЕТ и никто его не поставит
                    log.error("reconcile: СИРОТА ГОЛАЯ — позиция %s size=%s БЕЗ карточки И БЕЗ стопа на бирже: "
                              "НЕ защищена и НЕ управляется → СРОЧНАЯ ручная проверка (поставить стоп/закрыть)",
                              symbol, net_pos.get("size"))
                    event = "orphan_naked"
                    detail = "size=%s БЕЗ карточки и БЕЗ стопа" % net_pos.get("size")
                else:                                             # сирота со вшитым стопом — защита ЕСТЬ (verified), но не управляется
                    log.error("reconcile: СИРОТА — позиция %s size=%s БЕЗ карточки: вшитый стоп на бирже ЕСТЬ "
                              "(sl=%s, verified), но НЕ управляется (без целей/таймаута/cap) → тревога, ручная проверка",
                              symbol, net_pos.get("size"), sl)
                    event = "orphan_position"
                    detail = "size=%s без карточки (стоп есть sl=%s)" % (net_pos.get("size"), sl)
                try:
                    store.db.events_put(symbol=symbol, event=event, detail=detail)
                except Exception as ee:
                    log.warning("reconcile: events_put(orphan %s) пропущен: %s", symbol, ee)
                summary[symbol] = "orphan_naked" if naked else "orphan"
            continue
        net_pos = positions.get(symbol)
        live = (list(broker.get_open_orders(symbol))
                + list(broker.get_open_orders(symbol, order_filter="StopOrder")))
        corrected, action = reconcile_setup(symbol, snapshot, net_pos, live)
        if action == "exited":
            store.clear(symbol)
            try:
                store.db.orders_open_clear(symbol)        # панель «ждущие»: снять (сетап мёртв, 5.4d)
            except Exception as oe:
                log.warning("reconcile %s: orders_open_clear пропущен: %s", symbol, oe)
            log.info("reconcile %s: сетап вышел/мёртв в простое -> очищен", symbol)
        elif action == "kept":
            net = float(net_pos["size"]) if net_pos else 0.0
            open_qty = sum((corrected["legs"][lv].get("qty") or 0.0)
                           for lv in corrected["legs"] if corrected["legs"][lv].get("state") == OPEN)
            if net < open_qty - _QTY_TOL:         # биржа показывает МЕНЬШЕ открытых ног -> нога закрыта в простое
                log.warning("reconcile %s: нетто %.10g < открытых ног %.10g — нога закрыта в простое, "
                            "qty карточки завышен (пер-ножное разложение -> backlog D3)", symbol, net, open_qty)
            store.put(symbol, corrected)
        summary[symbol] = action
    return summary
