#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
broker.bybit_client — обёртка над Bybit v5 (pybit) для Пифагор V8.1.

Adapt из legacy V7-инфры + новое под V8.1 (ADR 0007, подтверждено докой Bybit v5):
- ONE-WAY режим (`positionIdx=0`); hedge для only-long НЕ нужен.
- Защитный стоп ВШИВАЕТСЯ в лимит-ордер (`stopLoss`, `tpslMode='Full'`, `slOrderType='Market'`,
  `slTriggerBy` из config) → позиция защищена с момента залива (15m-окно закрыто).
- Выходы по ногам — reduce-only условные ордера (`place_conditional`); перенос стопа открытой
  позиции — `set_trading_stop`; правка нестоявших ног — `amend_order`.

Живые ордера идут только на demo-домен (config.ops.USE_DEMO). Вывод средств не трогаем.
`http` инъектируется (для офлайн-тестов на моке); по умолчанию — реальный pybit HTTP.
"""
import re

import config

try:
    from pybit.unified_trading import HTTP
except Exception as e:  # pragma: no cover
    HTTP = None
    _IMPORT_ERR = e


def _s(v):
    """В строку (Bybit все числа принимает строками); None пробрасываем как None."""
    return None if v is None else str(v)


def _fnum(v):
    """Bybit-число (строка) → float; отсутствие/битое → None. Для НЕ-обязательных полей журнала закрытых
    сделок (qty/avg_entry/avg_exit): None честнее 0.0 (0.0 читался бы как «цена ноль»). Компаунд НЕ зависит."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class BybitClient:
    def __init__(self, http=None):
        if http is not None:          # инъекция для тестов/моков — реальный клиент не создаём
            self.http = http
            return
        if HTTP is None:  # pragma: no cover
            raise SystemExit(f"pybit не установлен: {_IMPORT_ERR}\npip install pybit")
        config.validate()
        # demo=True переключает SDK на api-demo.bybit.com. timeout — чтобы зависший сокет
        # не морозил heartbeat-поток (аудит Этапа 3).
        self.http = HTTP(
            demo=config.ops.USE_DEMO,
            api_key=config.ops.BYBIT_API_KEY,
            api_secret=config.ops.BYBIT_API_SECRET,
            timeout=20,
        )

    # ── режим позиции (one-way) ──────────────────────────────────────────────
    def ensure_one_way(self, coin="USDT"):
        """Гарантировать ONE-WAY (mode=0) на старте (ADR 0007). Возвращает {'ok': bool, ...}:
        ok=True — режим установлен ЛИБО уже one-way ('not modified' / retCode 110025 — НЕ ошибка);
        ok=False + 'err' — РЕАЛЬНАЯ ошибка (auth/режим/сеть). Вызывающий ОБЯЗАН прервать старт при ok=False
        (инвариант #11/#14, жёсткий one-way 5.5a): нельзя торговать positionIdx=0 против hedge-аккаунта.
        Раньше любая ошибка глоталась в {'note'} (мягкий WARN) — теперь fail-fast."""
        try:
            res = self.http.switch_position_mode(
                category=config.ops.CATEGORY, coin=coin, mode=0,
            )
            return {"ok": True, "result": res}
        except Exception as e:
            msg = str(e)
            # benign = аккаунт УЖЕ one-way. retCode 110025 как ТОКЕН (\b — иначе '1100250'/hex дают
            # ложноположительное → проглот РЕАЛЬНОЙ ошибки) ИЛИ pybit status_code, ИЛИ ТОЧНАЯ фраза Bybit.
            code = getattr(e, "status_code", None)
            benign = (code == 110025
                      or re.search(r"\b110025\b", msg) is not None
                      or "position mode is not modified" in msg.lower())
            if benign:
                return {"ok": True, "note": msg}
            return {"ok": False, "err": msg}

    # ── рынок ────────────────────────────────────────────────────────────────
    def get_instruments(self):
        """Все линейные перпы (постранично через nextPageCursor)."""
        out, cursor = [], None
        for _ in range(20):
            kw = dict(category=config.ops.CATEGORY, limit=1000)
            if cursor:
                kw["cursor"] = cursor
            res = self.http.get_instruments_info(**kw)["result"]
            out.extend(res.get("list", []))
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        return out

    def resolve_symbol(self, want, available_symbols):
        """Авторазрешение масштабных префиксов: BONKUSDT -> 1000BONKUSDT и т.п. Строго по основе."""
        if want in available_symbols:
            return want
        for pref in ("1000", "10000", "1000000"):
            if pref + want in available_symbols:
                return pref + want
        base = want.replace("USDT", "")
        candidates = {base + "USDT"} | {p + base + "USDT" for p in ("1000", "10000", "1000000")}
        for s in available_symbols:
            if s in candidates:
                return s
        return None

    def get_klines(self, symbol, interval=None, limit=1000, end=None):
        """Свечи в хронологии. interval: '240'=4h (сигнал) / '15'=15m (исполнение). Дефолт — config."""
        interval = interval or config.ops.INTERVAL
        kw = dict(category=config.ops.CATEGORY, symbol=symbol, interval=interval, limit=limit)
        if end is not None:
            kw["end"] = end
        rows = sorted(self.http.get_kline(**kw)["result"]["list"], key=lambda x: int(x[0]))
        return [
            {"time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
             "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])}
            for x in rows
        ]

    # ── счёт ─────────────────────────────────────────────────────────────────
    def get_balance(self):
        return self.http.get_wallet_balance(accountType="UNIFIED")["result"]

    def get_equity_usdt(self):
        """Equity счёта в USDT (с плавающим P&L) — для дашборда."""
        try:
            acct = self.get_balance()["list"][0]
            total = acct.get("totalEquity")
            usdt = next((c for c in acct.get("coin", []) if c.get("coin") == "USDT"), None)
            return {
                "total_equity": float(total) if total else None,
                "usdt_equity": float(usdt["equity"]) if usdt and usdt.get("equity") else None,
                "usdt_wallet": float(usdt["walletBalance"]) if usdt and usdt.get("walletBalance") else None,
            }
        except Exception as e:
            return {"err": str(e)}

    def get_positions(self):
        """Открытые позиции (settleCoin=USDT). Читает positionIdx (для reconcile). Ошибку
        НЕ глотаем в [{err}] — пробрасываем (нормализация контракта для reconcile/kill-switch)."""
        out = []
        for p in self.http.get_positions(category=config.ops.CATEGORY, settleCoin="USDT")["result"]["list"]:
            size = float(p.get("size", "0") or 0)
            if size == 0:
                continue
            out.append({
                "symbol": p.get("symbol"), "side": p.get("side"), "size": size,
                "position_idx": int(p.get("positionIdx", 0) or 0),
                "avg_price": float(p.get("avgPrice", "0") or 0),
                "mark_price": float(p.get("markPrice", "0") or 0),
                "unrealised_pnl": float(p.get("unrealisedPnl", "0") or 0),
                "leverage": p.get("leverage"),
                "stop_loss": float(p.get("stopLoss", "0") or 0),   # позиционный вшитый Full-стоп (0=нет) — инвариант покрытия 5.7
                "trailing_stop": float(p.get("trailingStop", "0") or 0),   # R8-трейл (путь Y): дистанция биржевого трейлинг-стопа (0=нет) — латч/сверка C3
                "active_price": float(p.get("activePrice", "0") or 0),      # цена активации трейлинга (0=нет)
            })
        return out

    def get_closed_pnl_total(self, start_ms=None):
        """Суммарный реализованный P&L окнами по 7 дней (лимит Bybit) + пагинация."""
        import time as _t
        try:
            total, n = 0.0, 0
            now_ms = int(_t.time() * 1000)
            week = 7 * 24 * 3600 * 1000
            win_start = start_ms if start_ms else now_ms - week
            while win_start < now_ms:
                win_end = min(win_start + week, now_ms)
                cursor = None
                for _ in range(20):
                    kw = dict(category=config.ops.CATEGORY, limit=100, startTime=win_start, endTime=win_end)
                    if cursor:
                        kw["cursor"] = cursor
                    res = self.http.get_closed_pnl(**kw)["result"]
                    for row in res.get("list", []):
                        total += float(row.get("closedPnl", "0") or 0); n += 1
                    cursor = res.get("nextPageCursor")
                    if not cursor:
                        break
                win_start = win_end
            return {"realised_pnl": round(total, 4), "closed_trades": n}
        except Exception as e:
            return {"err": str(e)}

    def get_closed_pnl_rows(self, start_ms=None, end_ms=None):
        """СТРОКИ закрытого PnL для delta-курсора компаунда (под-шаг 5a): список
        `{created_ms, order_id, closed_pnl}` (+ `symbol/side/qty/avg_entry/avg_exit` для журнала закрытых
        сделок trade_history_pnl — аддитивно, компаунд их игнорирует) (ASC по created_ms) ИЛИ `{'err': ...}` — ALL-OR-NOTHING
        (без частичных сумм: курсор не должен уехать за непрочитанное окно).

        Непересекающиеся 7д-окна `win_start = win_end + 1` (стык-сделка не дублируется при многодневном
        догоне). `start_ms is None` → последняя неделя (None-check, НЕ truthiness: `start_ms==0` ≠ «неделя»).
        Усечение пагинации (20 страниц И остался `nextPageCursor`) → `{'err'}` (потеря данных недопустима).
        Поля Bybit v5 /v5/position/closed-pnl: `createdTime`/`orderId`/`closedPnl` (execId здесь НЕТ; orderId
        НЕ уникален на строку — дедуп выше по (created_ms, orderId-set)). Имена подтвердить live-дампом."""
        import time as _t
        try:
            now_ms = int(end_ms) if end_ms is not None else int(_t.time() * 1000)
            week = 7 * 24 * 3600 * 1000
            win_start = (now_ms - week) if start_ms is None else int(start_ms)
            out = []
            while win_start <= now_ms:
                win_end = min(win_start + week, now_ms)
                cursor = None
                for _ in range(20):
                    kw = dict(category=config.ops.CATEGORY, limit=100, startTime=win_start, endTime=win_end)
                    if cursor:
                        kw["cursor"] = cursor
                    res = self.http.get_closed_pnl(**kw)["result"]
                    for r in res.get("list", []):
                        out.append({
                            "created_ms": int(r.get("createdTime") or 0),
                            "order_id": r.get("orderId"),
                            "closed_pnl": float(r.get("closedPnl", "0") or 0),
                            # trade_history_pnl (под-шаг 2): доп. поля для журнала закрытых сделок (persist —
                            # под-шаг 3). АДДИТИВНО: компаунд читает лишь created_ms/order_id/closed_pnl, эти
                            # игнорирует → бухгалтерия бит-в-бит. Fail-soft (_fnum→None); имена Bybit v5
                            # closed-pnl подтвердить live-дампом (side — сырая сторона, показ решает под-шаг 3/4).
                            "symbol": r.get("symbol"),
                            "side": r.get("side"),
                            "qty": _fnum(r.get("qty")),
                            "avg_entry": _fnum(r.get("avgEntryPrice")),
                            "avg_exit": _fnum(r.get("avgExitPrice")),
                        })
                    cursor = res.get("nextPageCursor")
                    if not cursor:
                        break
                else:
                    if cursor:                       # 20 страниц исчерпаны, данные остались → точный компаунд невозможен
                        return {"err": "closed-pnl pagination truncated (>20 страниц в окне)"}
                win_start = win_end + 1               # непересекающиеся окна
            out.sort(key=lambda x: x["created_ms"])
            return out
        except Exception as e:
            return {"err": str(e)}

    def get_executions(self, start_ms, end_ms):
        """СЫРЫЕ записи исполнений в окне execTime [start_ms, end_ms] — для REST-бэкфилла разрывов WS-тени
        (5.2 п7). Возвращает list dict'ов Bybit v5 /v5/execution/list (execId/orderLinkId/orderId/execPrice/
        execQty/execTime/execType/execFee/side/symbol) как есть — нормализует WS-тень (тот же путь, что для
        WS-кадра). Пагинация по cursor (bounded — окно разрыва мало). Ошибку НЕ глотаем: пробрасываем
        (WS-тень ловит best-effort, помечает окно backfilled=0)."""
        out = []
        cursor = None
        for _ in range(20):                            # bounded (окно мало; защита от петли пагинации)
            kw = dict(category=config.ops.CATEGORY, limit=100,
                      startTime=int(start_ms), endTime=int(end_ms))
            if cursor:
                kw["cursor"] = cursor
            res = self.http.get_executions(**kw)["result"]
            out.extend(res.get("list", []) or [])
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        else:                                          # 20 страниц исчерпаны, cursor остался → окно НЕ полностью
            if cursor:                                 # догнано; НЕ отдавать частично (иначе backfilled=1 при потере,
                raise RuntimeError(                    # завышение покрытия — недопустимо для гейта 5.6). Тень → backfilled=0.
                    "get_executions: пагинация усечена (>20 страниц) — окно не полностью покрыто")
        return out

    def apply_demo_funds(self):
        """Начислить demo-средства (только demo). pybit 5.16.0 `request_demo_trading_funds`
        не принимает сумму/монету — применяется ДЕФОЛТНЫЙ набор. Кастомная сумма — прямой
        вызов /v5/account/demo-apply-money (обёрткой pybit не поддержан, в бэклоге)."""
        if not config.ops.USE_DEMO:
            raise RuntimeError("apply_demo_funds только для demo-режима")
        return self.http.request_demo_trading_funds()

    # ── ордера ────────────────────────────────────────────────────────────────
    def place_limit(self, symbol, side, qty, price, stop_loss=None, take_profit=None,
                    link_id=None, position_idx=0, sl_trigger_by=None, reduce_only=False):
        """PostOnly лимит-нога. Защитный стоп ВШИТ (tpslMode='Full', slOrderType='Market',
        slTriggerBy из config) → позиция защищена в момент залива. side: 'Buy'/'Sell'."""
        kw = dict(
            category=config.ops.CATEGORY, symbol=symbol, side=side, orderType="Limit",
            qty=_s(qty), price=_s(price), timeInForce="PostOnly", positionIdx=position_idx,
        )
        if reduce_only:
            kw["reduceOnly"] = True
        if stop_loss is not None or take_profit is not None:
            kw["tpslMode"] = "Full"
            if stop_loss is not None:
                kw["stopLoss"] = _s(stop_loss)
                kw["slOrderType"] = "Market"
                kw["slTriggerBy"] = sl_trigger_by or config.execution.SL_TRIGGER_BY
            if take_profit is not None:
                kw["takeProfit"] = _s(take_profit)
                kw["tpOrderType"] = "Market"
        if link_id:
            kw["orderLinkId"] = link_id
        return self.http.place_order(**kw)

    def place_conditional(self, symbol, side, qty, trigger_price, trigger_direction,
                          reduce_only=True, order_type="Market", link_id=None,
                          position_idx=0, trigger_by=None):
        """Reduce-only УСЛОВНЫЙ ордер (выход ноги). triggerDirection: 1=цена растёт до
        триггера, 2=цена падает (стоп лонга вниз). triggerPrice превращает ордер в условный."""
        kw = dict(
            category=config.ops.CATEGORY, symbol=symbol, side=side, orderType=order_type,
            qty=_s(qty), triggerPrice=_s(trigger_price), triggerDirection=trigger_direction,
            reduceOnly=reduce_only, positionIdx=position_idx,
        )
        if order_type == "Limit":
            kw.setdefault("timeInForce", "GTC")
        if trigger_by:
            kw["triggerBy"] = trigger_by
        if link_id:
            kw["orderLinkId"] = link_id
        return self.http.place_order(**kw)

    def close_market(self, symbol, side, qty, position_idx=0, link_id=None):
        """Рыночное reduce-only закрытие позиции/ноги (CLOSE: timeout с открытыми ногами, аварийный
        выход). one-way positionIdx=0; лонг закрывается side='Sell'. reduceOnly страхует от пере-продажи."""
        kw = dict(
            category=config.ops.CATEGORY, symbol=symbol, side=side, orderType="Market",
            qty=_s(qty), reduceOnly=True, positionIdx=position_idx,
        )
        if link_id:
            kw["orderLinkId"] = link_id
        return self.http.place_order(**kw)

    def amend_order(self, symbol, order_id=None, link_id=None, price=None, qty=None,
                    trigger_price=None, stop_loss=None, take_profit=None):
        """Правка ещё не исполненного ордера/ноги (price/qty/триггер/привязанный TP-SL).
        Двигать стоп ОТКРЫТОЙ ПОЗИЦИИ — через set_trading_stop, не здесь."""
        kw = dict(category=config.ops.CATEGORY, symbol=symbol)
        if order_id:
            kw["orderId"] = order_id
        if link_id:
            kw["orderLinkId"] = link_id
        for k, v in (("price", price), ("qty", qty), ("triggerPrice", trigger_price),
                     ("stopLoss", stop_loss), ("takeProfit", take_profit)):
            if v is not None:
                kw[k] = _s(v)
        return self.http.amend_order(**kw)

    def set_trading_stop(self, symbol, stop_loss=None, take_profit=None, tpsl_mode="Full",
                         sl_size=None, tp_size=None, position_idx=0, sl_trigger_by=None,
                         trailing_stop=None, active_price=None):
        """Перенос TP/SL/ТРЕЙЛ УЖЕ ОТКРЫТОЙ позиции (бегунок ноги2 в БУ, нога3, shock; R8-трейл путь Y).
        Штатный путь Bybit для модификации стопа позиции. `trailing_stop`/`active_price` (R8-трейл, дизайн A):
        дистанция трейлинг-стопа в ЦЕНЕ (=TRAIL_R·(B−A)) + цена активации — СОсуществуют с `stop_loss`
        (трейлер ПОВЕРХ вшитого стопа; C0 подтверждает Q1). Поля уходят только при `is not None` (OFF-безопасно)."""
        kw = dict(category=config.ops.CATEGORY, symbol=symbol, positionIdx=position_idx,
                  tpslMode=tpsl_mode)
        if stop_loss is not None:
            kw["stopLoss"] = _s(stop_loss)
            kw["slTriggerBy"] = sl_trigger_by or config.execution.SL_TRIGGER_BY
        if take_profit is not None:
            kw["takeProfit"] = _s(take_profit)
        if sl_size is not None:
            kw["slSize"] = _s(sl_size)
        if tp_size is not None:
            kw["tpSize"] = _s(tp_size)
        if trailing_stop is not None:
            kw["trailingStop"] = _s(trailing_stop)   # дистанция трейлинг-стопа в цене (TRAIL_R·(B−A))
        if active_price is not None:
            kw["activePrice"] = _s(active_price)      # цена активации трейлинга (за вершиной B)
        return self.http.set_trading_stop(**kw)

    def cancel(self, symbol, order_id=None, link_id=None):
        kw = dict(category=config.ops.CATEGORY, symbol=symbol)
        if order_id:
            kw["orderId"] = order_id
        if link_id:
            kw["orderLinkId"] = link_id
        return self.http.cancel_order(**kw)

    def cancel_all(self, symbol):
        return self.http.cancel_all_orders(category=config.ops.CATEGORY, symbol=symbol)

    def get_open_orders(self, symbol, order_filter=None):
        """Стоящие ордера символа. order_filter='StopOrder' нужен, чтобы вернулись УСЛОВНЫЕ
        (reduce-only TP/SL) — без него Bybit v5 отдаёт только активные лимитки (read-side диффа)."""
        kw = dict(category=config.ops.CATEGORY, symbol=symbol)
        if order_filter:
            kw["orderFilter"] = order_filter
        return self.http.get_open_orders(**kw)["result"]["list"]

    def last_price(self, symbol):
        """Текущая последняя цена символа (PostOnly-гейт двойного захода 2b). None при сбое/пусто —
        вызывающий трактует как «отложить reprice» (не двигать ордер вслепую)."""
        try:
            lst = self.http.get_tickers(category=config.ops.CATEGORY, symbol=symbol)["result"]["list"]
            return float(lst[0]["lastPrice"]) if lst else None
        except Exception:
            return None

    def set_leverage(self, symbol, leverage):
        try:
            return self.http.set_leverage(
                category=config.ops.CATEGORY, symbol=symbol,
                buyLeverage=str(leverage), sellLeverage=str(leverage),
            )
        except Exception as e:
            return {"note": str(e)}  # часто «leverage not modified» — не критично
