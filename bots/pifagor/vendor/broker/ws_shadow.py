# -*- coding: utf-8 -*-
"""broker.ws_shadow — WS-тень (Веха 5.2 п6, measure-first; ADR 0014 — планируется).

Пассивный НАБЛЮДАТЕЛЬ приватного execution-стрима Bybit для ЗАМЕРА края Вехи 5.6 (лаг опроса + slip).
ВНЕ пути решений: НЕ импортирует lifecycle/executor/store, пишет только в ws_exec_log через WsExecFacade
(запись — под-шаг 4; здесь только подписка + отслеживание живости). Строится на pybit.unified_trading.
WebSocket (auth/ping/reconnect/ре-подписка — библиотека), поверх — тонкие best-effort хуки для:
  • свежести (last_ws_ms тикает от pong ~каждые ping_sec — execution-события редки на флэте, ими одними
    свежесть не удержать);
  • подтверждения подписки (subscribe_acked — «зелёный WS без активной подписки на execution» НЕ живой,
    иначе ws_exec_log молча пуст при мнимо-живом сокете);
  • счётчиков наблюдаемости (reconnect_count / msgs_received / drops).

is_alive() = subscribe_acked AND (now − last_ws_ms) < WS_STALENESS_MULT*WS_PING_SEC — вычисляется НА ЧТЕНИИ,
поэтому half-open сокет (перестал приходить pong) сам гаснет по устареванию last_ws_ms. Дедлайн клэмпится
снизу (mult≥1, ping≥1) — кривой env=0 не даёт мгновенно-протухшую тень.

ХРУПКОСТЬ: хуки трогают ПРИВАТНЫЕ атрибуты pybit (`_on_pong`/`callback`/`_on_error`) — точка риска при
апгрейде pybit. Каждый хук в try/except: при смене внутренностей библиотеки деградируем (лог + работа без
хука), воркер НЕ падает. Реальная проверка стрима — demo-смоук под-шага 7.
"""
import collections
import json
import logging
import threading
import time

import config

_DEFAULT_LOG = logging.getLogger("pifagor.ws_shadow")


class WsShadow:
    """Наблюдательный WS-стрим execution. Всё состояние живости — под _lock (консистентный снимок пары
    (subscribe_acked, last_ws_ms)). start()/stop() идемпотентны и best-effort (тень необязательна)."""

    def __init__(self, api_key, api_secret, logger=None, *, facade=None, prefix=None,
                 exec_history=None, queue_max=10000, demo=None, ping_sec=None, staleness_mult=None):
        self._api_key = api_key
        self._api_secret = api_secret
        self._log = logger or _DEFAULT_LOG
        self._facade = facade                # узкий WsExecFacade (write-only); None до плумбинга (под-шаг 5)
        self._prefix = prefix                # префикс НАШИХ orderLinkId; чужие/безлинковые → is_foreign=1
        self._exec_history = exec_history    # callable(start_ms,end_ms)->[raw exec] для REST-бэкфилла разрывов (5.2 п7)
        self._demo = config.ops.USE_DEMO if demo is None else demo
        self._ping_sec = int(config.ops.WS_PING_SEC if ping_sec is None else ping_sec)
        self._mult = int(config.ops.WS_STALENESS_MULT if staleness_mult is None else staleness_mult)
        self._lock = threading.Lock()
        self._ws = None
        self._queue = collections.deque(maxlen=int(queue_max))   # bounded: on_exec кладёт O(1), drain() пишет
        self._gap_start = None               # начало ОТКРЫТОГО разрыва WS (None = нет разрыва)
        self._pending_gaps = []              # закрытые окна [start,end] — REST-бэкфилл в drain() на главном потоке
        # состояние живости/наблюдаемости — читается/пишется ТОЛЬКО под _lock
        self._subscribe_acked = False
        self._last_ws_ms = None
        self._msgs_received = 0
        self._reconnect_count = 0
        self._drops = 0

    @staticmethod
    def _now():
        return int(time.time() * 1000)

    def _deadline_ms(self):
        # клэмп снизу (аудит п2): env mult/ping=0/отриц. не дают мгновенно-протухший дедлайн
        return max(self._mult, 1) * max(self._ping_sec, 1) * 1000

    # ── публичное API ──
    def is_alive(self, now_ms=None):
        """True ⇔ подписка на execution подтверждена И последний сигнал жизни свежее дедлайна. На чтении:
        мёртвый/half-open сокет (нет pong) сам даёт False по устареванию last_ws_ms. now_ms — для тестов."""
        now = self._now() if now_ms is None else now_ms
        with self._lock:
            if not self._subscribe_acked or self._last_ws_ms is None:
                return False
            return (now - self._last_ws_ms) < self._deadline_ms()

    def last_ws_ms(self):
        with self._lock:
            return self._last_ws_ms

    def stats(self):
        with self._lock:
            return {"subscribe_acked": self._subscribe_acked, "last_ws_ms": self._last_ws_ms,
                    "msgs_received": self._msgs_received, "reconnect_count": self._reconnect_count,
                    "drops": self._drops, "queued": len(self._queue),
                    "pending_gaps": len(self._pending_gaps), "connected": self._is_connected()}

    def drain(self):
        """Слить очередь в ws_exec_log через facade — зовётся ГЛАВНЫМ потоком из _poll_tick (под-шаг 5).
        Развязка от торгового лока: WS-поток только КЛАДЁТ в очередь (on_exec), запись (лок БД) — здесь,
        на главном потоке, пачкой одной транзакцией. Перед сливом — REST-бэкфилл закрытых разрывов WS (5.2 п7)
        в ту же очередь. Возвращает число вставленных строк. Без facade — no-op (очередь НЕ теряем; плумбинг
        подаёт facade в под-шаге 5). Сбой записи best-effort (тень необязательна)."""
        if self._facade is None:
            return 0
        self._backfill_pending_gaps()        # догнать пропущенное за разрывы (main thread) → ws_gaps + очередь
        with self._lock:
            if not self._queue:
                return 0
            rows = list(self._queue)
            self._queue.clear()
        try:
            return int(self._facade.ws_exec_put_many(rows) or 0)
        except Exception as e:                       # noqa: BLE001 — best-effort, тень необязательна
            self._log.warning("WS-тень: запись дренажа не удалась (возврат в очередь, рётрай на след. тике): %s", e)
            with self._lock:
                overflow = max(0, len(rows) + len(self._queue) - self._queue.maxlen)
                if overflow:
                    self._drops += overflow              # requeue сверх maxlen вытолкнет новейшие — честно как дроп
                self._queue.extendleft(reversed(rows))   # вернуть в ГОЛОВУ, порядок цел (новые за время записи — справа)
            return 0

    def _backfill_pending_gaps(self):
        """REST-догон пропущенного за разрывы WS (5.2 п7, ГЛАВНЫЙ поток из drain). Для каждого ЗАКРЫТОГО окна:
        запросить exec_history(start,end) → нормализовать (is_backfilled=1) → в очередь; записать ws_gaps
        (backfilled=1 при успехе, иначе 0 — Стадия B исключит НЕпокрытое окно из знаменателя покрытия).
        Best-effort: сбой окна не роняет тик. Идемпотентность по exec_id отсекает пересечения с WS-строками.
        КАП _MAX_GAPS окон за тик (остальные — на след. тик): REST-догон под reconnect-штормом НЕ должен
        откладывать 15m kill-switch (аудит границы Стадии A; дренаж и так перенесён в КОНЕЦ _poll_tick)."""
        _MAX_GAPS = 3
        with self._lock:
            gaps = self._pending_gaps[:_MAX_GAPS]
            self._pending_gaps = self._pending_gaps[_MAX_GAPS:]
        for start, end in gaps:
            backfilled = 0
            if self._exec_history is not None:
                try:
                    raw = self._exec_history(int(start), int(end)) or []
                    rows = self._normalize({"data": raw}, self._now())
                    for r in rows:
                        r["is_backfilled"] = 1
                    with self._lock:
                        for r in rows:
                            if len(self._queue) >= self._queue.maxlen:
                                self._drops += 1
                            self._queue.append(r)
                    backfilled = 1
                except Exception as e:               # noqa: BLE001 — best-effort; окно останется backfilled=0
                    self._log.warning("WS-тень: REST-бэкфилл окна [%s,%s] не удался: %s", start, end, e)
            try:
                self._facade.ws_gaps_put(gap_start_ms=start, gap_end_ms=end, backfilled=backfilled)
            except Exception as e:                   # noqa: BLE001 — окно НЕ должно исчезнуть из учёта покрытия
                self._log.warning("WS-тень: запись ws_gaps не удалась (окно на рётрай): %s", e)
                with self._lock:                     # рётрай на след. тике (re-fetch идемпотентен по exec_id);
                    self._pending_gaps.append((start, end))   # иначе строки есть, окна нет → покрытие завышено

    def start(self):
        """Поднять наблюдательный стрим (идемпотентно). Best-effort: сбой НЕ роняет воркер (тень
        необязательна, торговля идёт опросом). Реальная проверка — demo-смоук под-шага 7."""
        if self._ws is not None:
            return
        ws = None
        try:
            from pybit.unified_trading import WebSocket
            ws = WebSocket(channel_type="private", testnet=False, demo=self._demo,
                           api_key=self._api_key, api_secret=self._api_secret,
                           ping_interval=self._ping_sec)
            self._wire_hooks(ws)
            with self._lock:
                self._last_ws_ms = self._now()      # стартовая свежесть (сокет уже подключён в __init__ pybit)
            ws.execution_stream(callback=self._on_exec)
            self._ws = ws
            self._log.info("WS-тень: подключена, подписка на execution отправлена (demo=%s)", self._demo)
        except Exception as e:                       # noqa: BLE001 — best-effort, тень необязательна
            self._log.warning("WS-тень: старт не удался (best-effort, торговля не затронута): %s", e)
            if ws is not None:                       # частичный сбой: pybit коннектит+авторизует+пинг в __init__,
                try:                                 # execution_stream упал ПОСЛЕ — закрыть осиротевший сокет+таймер
                    ws.exit()                        # (иначе утечка авторизованного соединения + двойной старт на retry)
                except Exception:                    # noqa: BLE001
                    pass
            self._ws = None

    def stop(self):
        """Закрыть стрим (идемпотентно). Поток pybit — daemon, процесс не держит."""
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            ws.exit()
        except Exception as e:                       # noqa: BLE001
            self._log.warning("WS-тень: stop: %s", e)

    # ── внутреннее ──
    def _is_connected(self):
        ws = self._ws
        if ws is None:
            return False
        try:
            return bool(ws.is_connected())
        except Exception:                            # noqa: BLE001
            return False

    @staticmethod
    def _to_float(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _normalize(self, message, now_ms):
        """Bybit execution-кадр {topic, data:[{...}]} → строки WS_EXEC_COLS. is_foreign по префиксу линка
        (чужие/безлинковые — не наши; Стадия B исключит из знаменателя покрытия). Числа Bybit шлёт строками."""
        out = []
        data = message.get("data") if isinstance(message, dict) else None
        if not isinstance(data, list):
            return out
        for it in data:
            if not isinstance(it, dict):
                continue
            link = it.get("orderLinkId") or ""
            foreign = 0
            if self._prefix:                         # фильтр «наши vs чужие» (как reconcile/executor)
                foreign = 0 if link.startswith(self._prefix + "-") else 1
            out.append({
                "ts_ms": now_ms,
                "symbol": it.get("symbol"),
                "order_link_id": link or None,
                "order_id": it.get("orderId"),
                "exec_id": it.get("execId"),
                "side": it.get("side"),
                "exec_price": self._to_float(it.get("execPrice")),
                "exec_qty": self._to_float(it.get("execQty")),
                "exec_time_ms": self._to_int(it.get("execTime")),
                "exec_type": it.get("execType"),
                "exec_fee": self._to_float(it.get("execFee")),
                "is_foreign": foreign,
                "raw": json.dumps(it, ensure_ascii=False),
            })
        return out

    def _on_exec(self, message):
        """Колбэк execution-топика (WS-поток). Нормализует события, кладёт в bounded-очередь O(1) БЕЗ БД-лока
        (запись — главный поток в drain(): развязка от торгового лока). Пишем ВСЕ (вход+выход — выход несёт
        край). Любое execution-сообщение = сигнал жизни + подтверждение подписки."""
        try:
            now = self._now()
            rows = self._normalize(message, now)
            with self._lock:
                self._last_ws_ms = now
                self._subscribe_acked = True
                for r in rows:
                    self._msgs_received += 1
                    if len(self._queue) >= self._queue.maxlen:
                        self._drops += 1             # bounded: append вытолкнет старейшую строку
                    self._queue.append(r)
        except Exception as e:                       # noqa: BLE001
            self._log.warning("WS-тень on_exec: %s", e)

    def _note_pong(self, now_ms=None):
        """Сигнал жизни (pong/любое сообщение) — НЕ подтверждает подписку. Держит свежесть на флэте."""
        with self._lock:
            self._last_ws_ms = self._now() if now_ms is None else now_ms

    def _note_subscribe_ack(self, now_ms=None):
        """Подтверждение подписки на execution (ack сервера) + отметка живости. Если был ОТКРЫТ разрыв WS
        (после _on_error) — закрыть окно [gap_start, now] в очередь на REST-бэкфилл (5.2 п7)."""
        with self._lock:
            now = self._now() if now_ms is None else now_ms
            self._subscribe_acked = True
            self._last_ws_ms = now
            if self._gap_start is not None:
                self._pending_gaps.append((self._gap_start, now))
                self._gap_start = None

    def _wire_hooks(self, ws):
        """Тонкие best-effort хуки поверх ПРИВАТНЫХ методов pybit (переживают reconnect — атрибуты инстанса
        резолвятся на вызове). Оригинал ВСЕГДА вызывается (keepalive/routing pybit не ломаем)."""
        try:                                         # свежесть от pong (~каждые ping_sec)
            orig_pong = ws._on_pong
            def wrapped_pong():
                try:
                    self._note_pong()
                except Exception:                    # noqa: BLE001
                    pass
                return orig_pong()
            ws._on_pong = wrapped_pong
        except Exception as e:                       # noqa: BLE001
            self._log.warning("WS-тень: хук pong не установлен: %s", e)
        try:                                         # подтверждение подписки + свежесть от роутинговых сообщений
            orig_cb = ws.callback
            def wrapped_cb(message):
                try:
                    self._note_pong()                # роут-сообщение (auth/subscribe/data) — сигнал жизни; свежесть на флэте держит _on_pong (custom-pong сюда не доходит)
                    if isinstance(message, dict) and message.get("op") == "subscribe" \
                            and message.get("success") is True:
                        self._note_subscribe_ack()   # единственная подписка тени = execution
                except Exception:                    # noqa: BLE001
                    pass
                return orig_cb(message)
            ws.callback = wrapped_cb
        except Exception as e:                       # noqa: BLE001
            self._log.warning("WS-тень: хук callback не установлен: %s", e)
        try:                                         # счётчик реконнектов + открытие окна разрыва для бэкфилла
            orig_err = ws._on_error
            def wrapped_err(err):
                try:
                    with self._lock:
                        self._reconnect_count += 1
                        if self._gap_start is None:  # начало разрыва = последний известный «живой» момент
                            self._gap_start = self._last_ws_ms or self._now()
                except Exception:                    # noqa: BLE001
                    pass
                return orig_err(err)
            ws._on_error = wrapped_err
        except Exception as e:                       # noqa: BLE001
            self._log.warning("WS-тень: хук on_error не установлен: %s", e)
