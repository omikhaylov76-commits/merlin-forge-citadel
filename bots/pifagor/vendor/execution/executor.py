# -*- coding: utf-8 -*-
"""execution.executor — ИСПОЛНИТЕЛЬ V8.1 (Веха 3).

Тонкий идемпотентный слой: превращает Action-интенты машины выходов (execution.lifecycle) в
ордера Bybit v5 **one-way** через брокер (broker.bybit_client, фича 1). ТОЛЬКО исполняет — не решает
(это lifecycle), не считает размер ставки (sizing — risk_capital позже, берётся через шов), не хранит
состояние (state позже), не интеграционный цикл. one-way: positionIdx=0, без Sell/hedge (ADR 0007).

InstrumentMeta: округление цен/объёмов под tickSize/qtyStep инструмента (порт V7,
legacy_bot_reference/executor.py:23-62). Без него Bybit отвергает ордера.
Executor: place_setup/rebuild_setup/cancel_all_legs/timeout_setup (постановка) + update_targets/CLOSE
(идемпотентное ведение — под-шаг 3).
"""
import math
import time

import config
from logging_.trade_logger import get_logger
from .actions import (
    LV, PENDING, PLACE, REBUILD, UPDATE_TP_SL, CLOSE, SKIP_FILLED, REPRICE_ENTRY, open_legs,
)


def _round_step(value, step):
    """Округлить ВНИЗ к шагу инструмента (qtyStep / tickSize). floor: qty в рамках риск-бюджета,
    price сохраняет PostOnly/maker. step<=0 -> значение без изменений.

    `+1e-9` гасит float-погрешность деления (0.3/0.1==2.9999… -> floor 2): значение РОВНО на шаге
    не проваливается на целый шаг вниз. Эпсилон << любого реального под-шага, sub-step floor целый.
    (Отступление от V7-вербатим: у V7 этот баг есть; parity-причины тащить его НЕТ — движок не
    округляет под инструмент, округление — чисто live-необходимость.)"""
    if step is None or step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def _fmt(value, step):
    """Строка с числом знаков после точки по шагу (чтобы float-мусор не уходил в API)."""
    if step is None or step <= 0:
        return str(value)
    s = f"{step:.10f}".rstrip("0")
    decimals = len(s.split(".")[1]) if "." in s else 0
    return f"{value:.{decimals}f}"


class InstrumentMeta:
    """Точность/лимиты инструмента из instruments-info Bybit v5 (для валидных ордеров).
    Строится один раз на символ из broker.get_instruments(). Порт V7."""

    def __init__(self, info):
        lot = info.get("lotSizeFilter", {})
        prc = info.get("priceFilter", {})
        self.qty_step = float(lot.get("qtyStep", "0") or 0)
        self.min_qty = float(lot.get("minOrderQty", "0") or 0)
        # мин. НОТИОНАЛ (qty×price в USDT): linear-перп = minNotionalValue, spot = minOrderAmt (читаем оба,
        # defensive). 0 / поле отсутствует ⇒ гейт выключен (fail-safe, поведение как до фичи).
        self.min_notional = float(lot.get("minNotionalValue") or lot.get("minOrderAmt") or 0)
        self.tick_size = float(prc.get("tickSize", "0") or 0)

    def reject_reason(self, qty, price=None):
        """Причина отказа ноге по лимитам инструмента — ЕДИНЫЙ источник порогов. None ⇒ нога валидна.
        'min_qty' — округлённый объём ниже minOrderQty; 'min_notional' — нотионал (округлённый qty ×
        РЕАЛЬНО отправляемая цена = fix_price) ниже минимума биржи. price=None ⇒ нотионал НЕ проверяем
        (закрытия/reduce-only зовут fix_qty(qty) без цены — мелкий остаток закрываем всегда)."""
        q = _round_step(qty, self.qty_step)
        if self.min_qty and q < self.min_qty:
            return "min_qty"
        if self.min_notional and price is not None and q * _round_step(price, self.tick_size) < self.min_notional:
            return "min_notional"
        return None

    def fix_qty(self, qty, price=None):
        """Объём вниз к qtyStep. None, если нога отвергнута лимитами (min_qty / min_notional) — сигнал
        «пропусти ногу» (инвариант #8, расширен на нотионал). price=None ⇒ без нотионал-проверки."""
        return None if self.reject_reason(qty, price) else _round_step(qty, self.qty_step)

    def fix_price(self, price):
        """Цена вниз к tickSize."""
        return _round_step(price, self.tick_size)

    def qty_str(self, qty):
        return _fmt(qty, self.qty_step)

    def price_str(self, price):
        return _fmt(price, self.tick_size)


def _lv_tag(lv):
    """Тег уровня для стабильного orderLinkId (0.382 -> '0382')."""
    return str(lv).replace(".", "")


class Executor:
    """Исполняет Action-интенты lifecycle на Bybit ONE-WAY через брокер. ТОЛЬКО исполняет —
    не решает (lifecycle), не считает размер (sizing-шов), не хранит состояние (state).

    sizing — шов размера ставки: callable(symbol, lv, entry, stop) -> qty|None (risk_capital позже);
    нет sizing -> берём leg['qty']. meta_by_symbol: {symbol: InstrumentMeta}. link_prefix — префикс
    стабильного orderLinkId `{prefix}-{symbol}-{lv}-{role}` (role ∈ ent/tgt/stp).
    """

    SKIP_FILLED = SKIP_FILLED   # маркер «пере-якорь отменён, нога залилась» (= actions.SKIP_FILLED)

    def __init__(self, broker, meta_by_symbol, *, sizing=None, link_prefix="pf", logger=None, sl_trigger_by=None):
        self.broker = broker
        self.meta = meta_by_symbol
        self.sizing = sizing
        self.prefix = link_prefix
        self.log = logger or get_logger("pifagor.executor")
        # эффективный триггер стопа (крутилка SL_TRIGGER_BY); None ⇒ дефолт config. Executor ДОЛГОЖИВУЩИЙ —
        # 5.2 ОБНОВЛЯЕТ self.sl_trigger_by на старте 4h-цикла (иначе смена крутилки не применится до рестарта).
        self.sl_trigger_by = sl_trigger_by if sl_trigger_by is not None else config.execution.SL_TRIGGER_BY

    _last_gen = 0   # процесс-локальный монотонный трекер нонса: гарантирует, что два ПОДРЯД _gen() НИКОГДА не равны

    @classmethod
    def _gen(cls):
        # компактный нонс постановки (≤9 цифр): уникализирует orderLinkId ног, чтобы ре-постановка в 24h-окне Bybit
        # не отлетала как «duplicate orderLinkId» (110072). МОНОТОННО-возрастающий (при равной/откатившейся мс → last+1),
        # поэтому два ПОДРЯД нонса ВСЕГДА разные — иначе пере-якорь (cancel→place в одну мс на грубых/скачущих часах)
        # мог бы дать 110072 и молча потерять лесенку. Уникальность отдельного id — в пределах ~11.5 сут (1e9 мс) ≫ 24h-окна Bybit.
        g = int(time.time() * 1000) % 1_000_000_000
        if g <= cls._last_gen:
            g = (cls._last_gen + 1) % 1_000_000_000
        cls._last_gen = g
        return str(g)

    def _link(self, symbol, lv, role, gen=None):
        # gen=None → СТАРЫЙ стабильный формат (обратная совместимость: reconcile узнаёт до-нонс ордера, напр.
        # висящий ETH после деплоя). gen задан → нонс ПЕРЕД ролью: startswith("{prefix}-{symbol}-") и
        # endswith("-{role}") сохраняются (их и проверяет read_resting_orders); id никем не парсится на lv/role.
        core = f"{self.prefix}-{symbol}-{_lv_tag(lv)}"
        return f"{core}-{role}" if gen is None else f"{core}-{gen}-{role}"

    def _qty(self, symbol, meta, lv, entry, stop, leg):
        """Размер ноги: sizing-шов или leg['qty']; округление под лот. Возврат (qty, reason):
        reason ∈ {None, 'no_size', 'min_qty', 'min_notional'} — точная причина пропуска для лога.
        Нотионал считается по entry (реальная отправляемая цена; presize/place_setup — ЕДИНЫЙ шов)."""
        raw = self.sizing(symbol, lv, entry, stop) if self.sizing else leg.get("qty")
        if raw is None:
            return None, "no_size"
        q = meta.fix_qty(raw, entry)
        return q, (None if q is not None else meta.reject_reason(raw, entry))

    def presize(self, symbol, setup):
        """5.7 п.2 write-ahead: проставить qty (sizing) + link_id ногам БЕЗ ордеров — чтобы карта на диске
        имела размеры ДО постановки (иначе залив в окне до заполнения qty даёт qty=None → reconcile теряет
        залитую ногу). None, если ни одна нога не размещаема (нет меты / все ниже minOrderQty)."""
        meta = self.meta.get(symbol)
        if meta is None:
            return None
        setup["gen"] = self._gen()   # свежий нонс этой постановки (write-ahead) — все ноги берут его; переживёт на диск ДО ордеров
        placeable = 0
        for lv in LV:
            leg = setup["legs"][lv]
            if leg["state"] != PENDING:
                continue
            leg["link_id"] = self._link(symbol, lv, "ent", setup["gen"])
            leg["qty"], _ = self._qty(symbol, meta, lv, leg["entry"], setup["stop0"], leg)   # округлён; None если нога отвергнута лимитами (min_qty/min_notional)
            if leg["qty"] is not None:
                placeable += 1
        return setup if placeable else None

    def explain_unplaceable(self, symbol, setup):
        """Разбивка ПРИЧИН, почему ни одна нога не размещаема — для громкого fail-loud лога (когда presize=None).
        Сайд-эффектов нет (state/брокер не трогает). Возврат: 'min_notional×2, min_qty×1' | 'нет меты' |
        'нет PENDING-ног'. Причины берёт тем же `_qty`, что presize/place_setup — согласованно."""
        meta = self.meta.get(symbol)
        if meta is None:
            return "нет меты"
        tally = {}
        for lv in LV:
            leg = setup["legs"][lv]
            if leg["state"] != PENDING:
                continue
            _, reason = self._qty(symbol, meta, lv, leg["entry"], setup["stop0"], leg)
            if reason:
                tally[reason] = tally.get(reason, 0) + 1
        if not tally:
            return "нет PENDING-ног"
        return ", ".join(f"{r}×{n}" for r, n in tally.items())

    def place_setup(self, symbol, setup):
        """3 PostOnly BUY-лимитки со вшитым Full-стопом fib1.0 (БЕЗ статичного TP — parity-rewrite).
        Размер пере-считывается ВСЕГДА (rebuild на новой цене корректен; presize кладёт ту же цифру на
        карту для write-ahead). Пропускает ноги без размера / ниже minOrderQty. Возвращает setup, если
        встала хоть одна нога, иначе None. one-way: positionIdx=0, только long."""
        if setup["side"] != "long":
            self.log.warning("%s: executor one-way long-only, side=%s — пропуск", symbol, setup["side"])
            return None
        meta = self.meta.get(symbol)
        if meta is None:                                    # рассинхрон инструментов — мягкий пропуск, не KeyError
            self.log.warning("%s: нет InstrumentMeta — пропуск символа", symbol)
            return None
        stop_str = meta.price_str(meta.fix_price(setup["stop0"]))
        if not setup.get("gen"):
            setup["gen"] = self._gen()   # прямой place без presize (страховка): проставить нонс; presize/rebuild уже проставляют свой
        placed = 0
        for lv in LV:
            leg = setup["legs"][lv]
            if leg["state"] != PENDING:
                continue
            qty, reason = self._qty(symbol, meta, lv, leg["entry"], setup["stop0"], leg)   # ВСЕГДА пере-считываем под ТЕКУЩИЙ entry (rebuild корректен)
            if qty is None:
                self.log.info("%s lv=%s: %s — пропуск ноги", symbol, lv, reason)   # точная причина: no_size/min_qty/min_notional
                continue
            link = self._link(symbol, lv, "ent", setup["gen"])
            try:
                res = self.broker.place_limit(
                    symbol, "Buy", meta.qty_str(qty), meta.price_str(meta.fix_price(leg["entry"])),
                    stop_loss=stop_str, link_id=link, position_idx=0, sl_trigger_by=self.sl_trigger_by,
                )
            except Exception as e:                       # сбой брокера на ноге -> пропуск (уже выставленные живут, не сирота)
                self.log.warning("%s lv=%s: place_limit не прошёл (%s) — нога пропущена", symbol, lv, e)
                continue
            leg["order_id"] = (res or {}).get("result", {}).get("orderId")
            leg["link_id"] = link
            leg["qty"] = qty
            placed += 1
        return setup if placed else None

    def cancel_all_legs(self, symbol, setup):
        """Отменить СТОЯЩИЕ (не залитые) лимитки. Залитые ноги не трогаем. try/except на ногу."""
        for lv in LV:
            leg = setup["legs"][lv]
            if leg["state"] != PENDING or not leg.get("link_id"):
                continue
            try:
                self.broker.cancel(symbol, link_id=leg["link_id"])
                leg["order_id"] = None
                leg["link_id"] = None
            except Exception as e:
                self.log.warning("%s lv=%s: cancel не прошёл: %s", symbol, lv, e)

    def rebuild_setup(self, symbol, setup):
        """Пере-якорь до commit: если ХОТЬ ОДНА нога уже не pending (залилась в гонке) -> SKIP_FILLED
        (ничего не трогаем, C1/инвариант #9); иначе отменить стоящие + поставить новую сетку.
        -> setup | SKIP_FILLED | None."""
        if any(setup["legs"][lv]["state"] != PENDING for lv in LV):
            return self.SKIP_FILLED
        self.cancel_all_legs(symbol, setup)
        setup["gen"] = self._gen()   # ПЕРЕ-ЯКОРЬ: свежий нонс → новые id не столкнутся с только что отменёнными в 24h-окне Bybit
        return self.place_setup(symbol, setup)

    def timeout_setup(self, symbol, setup):
        """Освободить слот: отменить стоящие ноги. Рыночное закрытие ОТКРЫТЫХ ног — путь CLOSE:
        lifecycle на timeout по закрытым 4h эмитит close(still_open, 'timeout'), его исполняет
        execute(...CLOSE...) -> self.close(...). Здесь — только отмена нестоявших лимиток."""
        self.cancel_all_legs(symbol, setup)

    # ── идемпотентное ведение (под-шаг 3) ───────────────────────────────────────
    def _close_link(self, symbol):
        # per-call nonce (мс): каждый рыночный close — уникальный orderLinkId → дубль-CLOSE на рестарте/ретрае
        # НЕ отлетит как «duplicate orderLinkId» в 24h-окне Bybit (Q1, под-шаг 4b). reduce-only страхует от
        # пере-закрытия; повторная финализация гейтится очисткой карты (state.clear), не стабильностью linkId.
        return f"{self.prefix}-{symbol}-cls-{int(time.time() * 1000)}"

    def _desired_pool(self, symbol, setup, meta):
        """Желаемый набор reduce-only условных {linkId: {trigger,qty,direction}} из КАРТОЧКИ
        (авторитет — карточка, не payload -> convergent): tgt по leg['target'] (TP вверх, dir=1)
        каждой открытой ноги; stp по leg['resting_stop'] (SL вниз, dir=2) ТОЛЬКО после миграции в
        пул (до неё стоп держит вшитый Full). Цены/объёмы округлены под инструмент и в строку —
        чтобы diff сравнивался байт-в-байт с нормализованным live."""
        desired = {}
        migrated = setup.get("migrated")
        for lv in open_legs(setup):
            leg = setup["legs"][lv]
            if leg.get("qty") is None:
                continue
            q = meta.fix_qty(leg["qty"])
            if q is None:
                continue
            qs = meta.qty_str(q)
            if leg.get("target") is not None:
                t = meta.price_str(meta.fix_price(leg["target"]))
                desired[self._link(symbol, lv, "tgt", setup.get("gen"))] = {"trigger": t, "qty": qs, "direction": 1}
            if migrated and leg.get("resting_stop") is not None:
                s = meta.price_str(meta.fix_price(leg["resting_stop"]))
                desired[self._link(symbol, lv, "stp", setup.get("gen"))] = {"trigger": s, "qty": qs, "direction": 2}
        return desired

    def _live_pool(self, symbol, meta):
        """Стоящие условные нашего пула (роль tgt/stp нашего префикса) {linkId: {trigger,qty}},
        нормализованные ТЕМ ЖЕ форматтером (иначе API-строка '110.00' vs '110.0' вечно «различается»).
        Условные не видны без orderFilter='StopOrder' (read-side диффа)."""
        try:
            raw = self.broker.get_open_orders(symbol, order_filter="StopOrder")
        except Exception as e:
            self.log.warning("%s: get_open_orders не прошёл: %s", symbol, e)
            return {}
        idx = {}
        pfx = f"{self.prefix}-{symbol}-"
        for o in raw:
            link = o.get("orderLinkId")
            if not link or not link.startswith(pfx):
                continue
            if not (link.endswith("-tgt") or link.endswith("-stp")):
                continue
            trig, qty = o.get("triggerPrice"), o.get("qty")
            idx[link] = {
                "trigger": meta.price_str(float(trig)) if trig not in (None, "") else None,
                "qty": meta.qty_str(float(qty)) if qty not in (None, "") else None,
            }
        return idx

    def _reconcile_pool(self, symbol, desired, live):
        """Convergent diff: нет->place_conditional один раз; различие->amend_order на месте (НЕ
        пересоздавать); идентично->no-op (тихий тик = ноль вызовов); лишнее (наш tgt/stp не в
        desired)->cancel. amend сработавшего ('order not exists/too late') -> лог + пере-чтение на
        следующем тике, НИКОГДА не слепой re-create (это и есть баг «задвоить»)."""
        for link, d in desired.items():
            cur = live.get(link)
            if cur is None:
                self.broker.place_conditional(
                    symbol, "Sell", d["qty"], d["trigger"], d["direction"],
                    reduce_only=True, order_type="Market", link_id=link,
                    position_idx=0, trigger_by=self.sl_trigger_by,
                )
            elif cur["trigger"] != d["trigger"] or cur["qty"] != d["qty"]:
                try:
                    self.broker.amend_order(symbol, link_id=link,
                                            trigger_price=d["trigger"], qty=d["qty"])
                except Exception as e:
                    self.log.warning("%s %s: amend не прошёл (%s) — reconcile на след. тике", symbol, link, e)
            # else identical -> no-op (тихий тик)
        for link in live:
            if link not in desired:
                try:
                    self.broker.cancel(symbol, link_id=link)
                except Exception as e:
                    self.log.warning("%s %s: cancel лишнего не прошёл: %s", symbol, link, e)

    def update_targets(self, symbol, setup, updates=None):
        """UPDATE_TP_SL: привести стоящие reduce-only TP/SL к желаемому (из карточки) идемпотентным
        diff'ом. updates — триггер/подсказка lifecycle; авторитет желаемого — карточка (convergent).

        Миграция Full->пул при ПЕРВОЙ дивергенции пер-ножного стопа (бегунок в БУ: resting_stop=entry
        != stop0): СНАЧАЛА выставить пуловые stp ВСЕМ открытым ногам, ПОТОМ снять вшитый Full-стоп
        (set_trading_stop stopLoss='0') — кратко двойная защита, голой позиции нет ни мгновения."""
        meta = self.meta.get(symbol)
        if meta is None:
            self.log.warning("%s: нет InstrumentMeta — пропуск update_targets", symbol)
            return None
        stop0 = setup["stop0"]
        migrating = False
        if not setup.get("migrated") and any(
            setup["legs"][lv].get("resting_stop") is not None
            and setup["legs"][lv]["resting_stop"] != stop0
            for lv in open_legs(setup)
        ):
            setup["migrated"] = True                 # _desired_pool теперь включает stp
            migrating = True
        desired = self._desired_pool(symbol, setup, meta)
        live = self._live_pool(symbol, meta)
        self._reconcile_pool(symbol, desired, live)
        if migrating:                                # пуловые стопы стоят -> снять вшитый Full ТОЛЬКО если пул покрыл net
            if self._pool_covers_net(symbol, desired):
                try:
                    self.broker.set_trading_stop(symbol, stop_loss="0", position_idx=0, sl_trigger_by=self.sl_trigger_by)
                except Exception as e:
                    self.log.warning("%s: снятие Full-стопа при миграции не прошло: %s", symbol, e)
            else:                                    # 5.7 п.1 guard: пул < net (карта занижена?) → Full НЕ снимаем
                self.log.warning("%s: миграция — пул -stp покрывает < net → Full НЕ снимаем "
                                 "(ПОСТОЯННАЯ двойная защита; НЕ авто-снимается — покрытие держит инвариант-свип _ensure_stop_coverage)", symbol)
        return setup

    def _pool_covers_net(self, symbol, desired):
        """Guard снятия Full при миграции (5.7 п.1): True, если Σ qty желаемых -stp >= текущий нетто позиции.
        Нетто недоступен (raise) → False (fail-safe: НЕ снимать Full, оставить двойную защиту)."""
        try:
            positions = self.broker.get_positions()
        except Exception as e:
            self.log.warning("%s: get_positions при guard миграции не прошёл (%s) → Full не снимаем", symbol, e)
            return False
        net = 0.0
        for p in positions:
            if p.get("symbol") == symbol:
                net = float(p.get("size") or 0)
                break
        stp_qty = 0.0
        for link, d in desired.items():
            if link.endswith("-stp"):
                try:
                    stp_qty += float(d["qty"])
                except (TypeError, ValueError, KeyError):
                    pass
        return stp_qty >= net - 1e-9

    # ── R8 путь Y (Дизайн A): нативный трейлер Bybit соло-бегунка (под-шаг C3) ───
    def _warn_arm(self, setup, fmt, *args):
        """Throttle: «не ставим / отказ» трейлера логируем ОДИН раз на сетап (латч trail_arm_warned) —
        иначе спам ~1/мин до 72 4h-баров. Сброс латча — при успешном арме/adopt (pop) и финализации (state.clear)."""
        if setup.get("trail_arm_warned"):
            return
        setup["trail_arm_warned"] = True
        self.log.warning(fmt, *args)

    def maybe_arm_trailer(self, symbol, setup, trail_r, leg2_ext, position):
        """R8 путь Y (Дизайн A): армировать НАТИВНЫЙ трейлер Bybit для СОЛО-бегунка за вершиной B —
        дистанция trail_r·|B−A| ПОВЕРХ вшитого Full-стопа (физически = движковый max(estop,trail)). Ставит
        трейлер ПЕРВЫМ, затем латчит trail_armed (leg_targets снимет фикс-TP след. ретаргетом) + снимает
        резтинг-0.618 -ent (гэп-защита). Идемпотентно: trailing_stop уже >0 (краш между set и persist) →
        adopt без пере-set. OFF (trail_r<=0) / не-соло / migrated / уже-armed → no-op. -> setup (мутирован) | None.

        position — дикт позиции этого тика (broker.get_positions): нужен для БИРЖЕВОЙ сверки соло (net≈бегунок;
        карта врёт при лаге списка ордеров Bybit — MAJOR-B) и adopt (trailing_stop). None → арм отложен (fail-safe).
        Гейт not migrated (MAJOR-A): флаг-ON на уже-БУ-мигрированном бегунке НЕ трогаем (добьёт baseline)."""
        if trail_r <= 0.0:
            return None
        if setup.get("trail_armed"):
            # defensive re-cancel: арм-отмена резтинг-0.618 могла промахнуться (best-effort) → добить, пока
            # армированы (иначе на дампе после трейл-выхода стоячая BUY-лимитка откроет новый лонг до финализации).
            if any(setup["legs"][lv].get("state") == PENDING and setup["legs"][lv].get("link_id")
                   for lv in setup["legs"]):
                self.cancel_all_legs(symbol, setup)
                return setup
            return None
        if not (setup.get("committed") and setup.get("profit_taken") and setup.get("beyond_B")):
            return None
        if setup.get("migrated"):
            return None                                  # MAJOR-A: мид-ride уже-БУ-бегунок добивает baseline
        opens = open_legs(setup)
        if len(opens) != 1:
            return None                                  # трейлер позиц.-уровня тянет ВСЮ позицию → только соло (карта)
        runner = opens[0]
        eff_leg2 = leg2_ext if leg2_ext is not None else config.execution.LEG2_EXT
        is_ride = ((runner == 0.5 and eff_leg2 > 0.0) or (runner == 0.618 and config.execution.LEG3_MODE == "ext"))
        if not is_ride:
            return None
        meta = self.meta.get(symbol)
        if meta is None:
            return None
        runner_qty = setup["legs"][runner].get("qty")
        if runner_qty is None:
            return None
        if position is None:                             # без снимка позиции сверку соло не сделать → отложить
            self._warn_arm(setup, "%s: трейлер — нет снимка позиции, арм отложен", symbol)
            return None
        net = float(position.get("size") or 0)
        step = meta.qty_step or 0.0
        if net > float(runner_qty) + step + 1e-9:        # MAJOR-B: биржа видит >1 ноги (0.618 залилась, лаг карты)
            self._warn_arm(setup, "%s: трейлер — биржевой нетто %.10g > бегунка %.10g (не соло) → не армируем",
                           symbol, net, float(runner_qty))
            return None
        if float(position.get("trailing_stop") or 0) > 0:   # MAJOR-B idempotent adopt: трейлер уже на бирже → усыновить
            setup["trail_armed"] = True
            setup.pop("trail_arm_warned", None)
            self.cancel_all_legs(symbol, setup)
            self.log.info("%s: трейлер уже на бирже (trailing_stop>0) → adopt (латч armed + 0.618 снят)", symbol)
            return setup
        dist_str = meta.price_str(meta.fix_price(trail_r * abs(float(setup["B"]) - float(setup["A"]))))
        if float(dist_str) <= 0:                         # дистанция округлилась в 0 (крошечный |B−A| под тик)
            self._warn_arm(setup, "%s: трейл-дистанция округлилась в 0 → трейлер не ставим", symbol)
            return None
        try:                                             # трейлер БЕЗ activePrice (за B → активация сразу, C0-рефайн)
            self.broker.set_trading_stop(symbol, trailing_stop=dist_str, position_idx=0)
        except Exception as e:
            self._warn_arm(setup, "%s: постановка трейлера не прошла (%s) — baseline держим, ретрай", symbol, e)
            return None
        setup["trail_armed"] = True                      # трейлер стоит → латч (leg_targets снимет фикс-TP след. ретаргетом)
        setup.pop("trail_arm_warned", None)
        self.cancel_all_legs(symbol, setup)              # соло-ride: снимает ТОЛЬКО резтинг-0.618 -ent (гэп-защита)
        self.log.info("%s: трейлер армирован (dist=%s, trail_r=%s) — фикс-цель снимется ретаргетом", symbol, dist_str, trail_r)
        return setup

    def _cancel_pool(self, symbol, setup, meta):
        """Снять все стоящие условные нашего пула (tgt/stp) по символу."""
        for link in self._live_pool(symbol, meta):
            try:
                self.broker.cancel(symbol, link_id=link)
            except Exception as e:
                self.log.warning("%s %s: cancel пула не прошёл: %s", symbol, link, e)

    def close(self, symbol, setup, legs, reason="complete"):
        """CLOSE: рыночное reduce-only закрытие ОТКРЫТЫХ ног + очистка. legs — список lv открытых
        ног; пустой (completion-латч) -> только отмена/финализация, БЕЗ рынка. qty закрытия — Σ
        leg['qty'] открытых (живую позицию арбитрирует state позже; reduce-only страхует на бирже)."""
        meta = self.meta.get(symbol)
        if meta is None:
            self.log.warning("%s: нет InstrumentMeta — финализирую без рыночного закрытия", symbol)
            setup["closed"] = True
            return setup
        if legs:
            total = 0.0
            for lv in legs:
                leg = setup["legs"].get(lv)
                if leg is None or leg.get("qty") is None:
                    continue
                q = meta.fix_qty(leg["qty"])
                if q:
                    total += q
            q_close = meta.fix_qty(total) if total else None
            if q_close:
                self.broker.close_market(symbol, "Sell", meta.qty_str(q_close),
                                         position_idx=0, link_id=self._close_link(symbol))
            else:
                self.log.info("%s CLOSE(%s): нет объёма открытых ног — только отмена", symbol, reason)
        self.cancel_all_legs(symbol, setup)
        self._cancel_pool(symbol, setup, meta)
        if legs and not setup.get("migrated"):       # позиция закрыта рынком; снять вшитый Full, если ещё армирован
            try:
                self.broker.set_trading_stop(symbol, stop_loss="0", position_idx=0, sl_trigger_by=self.sl_trigger_by)
            except Exception as e:
                self.log.warning("%s CLOSE: снятие Full-стопа не прошло: %s", symbol, e)
        setup["closed"] = True
        return setup

    # ── двойной заход: пере-цена resting entry-лимитки (под-шаг 2b) ──────────────
    def reprice_plan(self, symbol, setup, lv, new_price):
        """РЕШЕНИЕ (без мутаций брокера): двигать ли resting entry-лимитку lv на new_price=thr.
        PostOnly-гейт: двигаем ТОЛЬКО когда рынок ВЫШЕ порога — иначе amend-вверх ПЕРЕСЕЧЁТ рынок и Bybit
        СНИМЕТ ордер (retCode 0 ВРЁТ — demo-эксперимент F-B1). + дедуп (уже на пороге) + qty от ХУДШЕЙ цены.
        -> {'thr','qty','plain'} | None (не двигаем; ордер остаётся на плоской цене, ретрай след. тик)."""
        leg = setup["legs"].get(lv)
        if leg is None or leg["state"] != PENDING or not leg.get("order_id"):
            return None                                    # нет resting entry-ордера — двигать нечего
        meta = self.meta.get(symbol)
        if meta is None:
            self.log.warning("%s: нет InstrumentMeta — reprice пропущен", symbol)
            return None
        thr = meta.fix_price(new_price)
        plain = float(leg["entry"])
        if thr is None:
            return None
        if abs(plain - float(thr)) < 1e-6:                 # дедуп: уже на пороге (конвергентный re-emit → no-op)
            return None
        px = self.broker.last_price(symbol)
        if px is None:
            self.log.warning("%s lv=%s: нет цены — reprice отложен", symbol, lv)
            return None
        if px <= float(thr):                               # рынок НЕ выше порога → amend пересечёт → отложить
            self.log.info("%s lv=%s: reprice отложен (цена %.10g <= порог %.10g, PostOnly-кросс) — ретрай",
                          symbol, lv, px, float(thr))
            return None
        q, reason = self._qty(symbol, meta, lv, thr, setup["stop0"], leg)   # qty от ХУДШЕЙ (сдвинутой) цены
        if q is None:
            self.log.info("%s lv=%s: reprice пропущен (%s) — ордер оставлен на плоской цене", symbol, lv, reason)
            return None
        return {"thr": float(thr), "qty": q, "plain": plain}

    def _entry_order_alive(self, symbol, link):
        """Стоит ли ещё наша entry-лимитка (по orderLinkId)? Regular-ордера (без StopOrder-фильтра).
        Сбой чтения → True (fail-safe: не знаем → НЕ re-place, чтобы не задвоить ордер)."""
        if not link:
            return False
        try:
            return any(o.get("orderLinkId") == link for o in self.broker.get_open_orders(symbol))
        except Exception as e:
            self.log.warning("%s: get_open_orders (reprice re-read) не прошёл: %s — считаем ордер живым", symbol, e)
            return True

    def reprice_apply(self, symbol, setup, lv, plan):
        """ИСПОЛНЕНИЕ: подвинуть resting entry-лимитку lv на plan['thr'] через amend. Карта (entry/qty) уже
        WRITE-AHEAD в цикле. ПОСЛЕ amend ПЕРЕ-ЧИТАЕМ ордер (retCode 0 НЕ значит «жив» — кросс СНИМАЕТ,
        demo-эксперимент F-B1): исчез → ОТКАТ на ПЛОСКУЮ цену (безопасно = обычный вход; худшее — пропустить
        допуск этот тик, конвергентный re-emit ретрайнет). -> setup (order_id/link/entry/qty обновлены)."""
        meta = self.meta.get(symbol)
        if meta is None:
            return setup
        leg = setup["legs"][lv]
        thr, qty, plain = plan["thr"], plan["qty"], plan["plain"]
        link = leg.get("link_id")
        amend_ok = True
        try:
            self.broker.amend_order(symbol, order_id=leg.get("order_id"),
                                    price=meta.price_str(meta.fix_price(thr)), qty=meta.qty_str(qty))
        except Exception as e:
            self.log.warning("%s lv=%s: reprice amend не прошёл (%s) — пере-проверка ордера", symbol, lv, e)
            amend_ok = False
        if self._entry_order_alive(symbol, link):
            if not amend_ok:                               # amend упал (сеть) → ордер остался на ПЛОСКОЙ →
                pq, _ = self._qty(symbol, meta, lv, plain, setup["stop0"], leg)   # карту вернуть с thr на plain (синхронно бирже)
                leg["entry"] = plain
                leg["qty"] = pq
                self.log.warning("%s lv=%s: amend упал, ордер жив на плоской → карта возвращена на plain", symbol, lv)
            return setup                                   # ордер жив (thr при успехе / plain при провале — карта синхронна)
        # ордер ИСЧЕЗ (PostOnly-кросс снял, retCode врал) → ОТКАТ: re-place на ПЛОСКОЙ цене
        self.log.warning("%s lv=%s: entry-ордер исчез после amend (PostOnly-кросс) → откат на плоскую %.10g",
                         symbol, lv, plain)
        pq, _ = self._qty(symbol, meta, lv, plain, setup["stop0"], leg)
        leg["entry"] = plain
        leg["qty"] = pq
        leg["order_id"] = None
        leg["link_id"] = None
        if pq is None:
            self.log.warning("%s lv=%s: плоская нога не размещаема — оставлена без ордера (reconcile/таймаут)", symbol, lv)
            return setup
        setup["gen"] = self._gen()
        newlink = self._link(symbol, lv, "ent", setup["gen"])
        stop_str = meta.price_str(meta.fix_price(setup["stop0"]))
        try:
            res = self.broker.place_limit(symbol, "Buy", meta.qty_str(pq), meta.price_str(meta.fix_price(plain)),
                                          stop_loss=stop_str, link_id=newlink, position_idx=0, sl_trigger_by=self.sl_trigger_by)
            leg["order_id"] = (res or {}).get("result", {}).get("orderId")
            leg["link_id"] = newlink
        except Exception as e:
            self.log.warning("%s lv=%s: re-place плоской ноги не прошёл (%s) — без ордера, reconcile/ретрай", symbol, lv, e)
        return setup

    def execute(self, symbol, setup, action):
        """Диспетчер Action.kind -> исполнитель. -> setup | SKIP_FILLED | None. PLACE/REBUILD берут
        полный setup (payload информационный), UPDATE_TP_SL/CLOSE — payload. NONE/SKIP_FILLED no-op."""
        kind = action.kind
        if kind == PLACE:
            return self.place_setup(symbol, setup)
        if kind == REBUILD:
            return self.rebuild_setup(symbol, setup)
        if kind == UPDATE_TP_SL:
            return self.update_targets(symbol, setup, action.payload.get("updates", []))
        if kind == CLOSE:
            return self.close(symbol, setup, action.payload.get("legs", []),
                              action.payload.get("reason", "complete"))
        if kind == REPRICE_ENTRY:                        # 2b: живой путь — _exec_reprice (write-ahead) в цикле;
            return None                                  # сюда штатно НЕ доходит (перехват в _exec_action), defensive no-op
        self.log.debug("%s: %s — no-op", symbol, kind)   # NONE / SKIP_FILLED
        return None
