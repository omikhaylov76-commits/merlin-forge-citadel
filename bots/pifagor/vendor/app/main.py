#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.main — точка входа worker-сервиса Пифагор V8.1 (START_FILE=app/main.py).

Веха 3 фича 2 — 15m-планировщик: порядок старта (validate -> singleton-lock ->
demo/mainnet домены -> UTC-warn) + лёгкий цикл, выровненный к закрытию 15m-свечи
(EXEC_INTERVAL). По каждой включённой монете тянет свежую ЗАКРЫТУЮ свечу и отдаёт её
в ШОВ on_candle. Сам шов сейчас — намеренная заглушка-лог: signal/lifecycle/executor/
sizing/ledger/killswitch подключатся сюда на фичах 3–5 (parity-закон — выходы считает
движок, не переписываем).

Запуск:
    python3 app/main.py            # бесконечный 15m-цикл (выравнивание к границе свечи)
    python3 app/main.py --once     # один тик и чистый выход 0 (smoke)
"""
import os
import sys
import time

# Корень репозитория в путь импорта (скрипт запускается как app/main.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from config import knobs  # noqa: E402
from logging_.trade_logger import get_logger  # noqa: E402
from storage.db import DB, acquire_singleton  # noqa: E402
from broker.bybit_client import BybitClient  # noqa: E402
from market.market_data import (  # noqa: E402
    MarketData, check_utc_alignment, next_boundary_ms, interval_ms,
)
from state.config import ConfigStore  # noqa: E402
from state.store import StateStore  # noqa: E402
from state.capital import CapitalStore  # noqa: E402
from state.reconcile import reconcile_on_start  # noqa: E402
from risk_capital.ledger import Ledger  # noqa: E402
from risk_capital.providers import make_working_provider  # noqa: E402
from risk_capital import killswitch  # noqa: E402
from execution import protection  # noqa: E402
from execution.actions import PENDING  # noqa: E402
from execution.executor import Executor, InstrumentMeta  # noqa: E402
from app.cycle import (  # noqa: E402
    run_4h_cycle, run_15m_tick, maybe_flatten_all, warm_start_auto, write_warm_candidates,
    write_scan_snapshot, maybe_warm, journal_sync, JOURNAL_INTERVAL_MS,
)
from market.klines_4h import FOUR_HOUR_MS  # noqa: E402


class PifagorApp:
    """Оркестратор: порядок старта + 15m-цикл подтягивания закрытых свечей в шов."""

    BOUNDARY_BUFFER_SEC = 5   # буфер после границы 15m — дать Bybit дозакрыть свечу (как V7)

    def __init__(self, broker=None, db=None):
        self._process_start_ms = int(time.time() * 1000)    # bot_health: истинный старт процесса (→ аптайм/«проснулся»)
        self._last_exchange_ok_ms = None                    # bot_health: время последнего успешного вызова Bybit (штамп в _poll_tick)
        self.log = get_logger("pifagor.worker")

        # 1. fail-fast: без ключей / при кривых knobs validate() бросит SystemExit.
        config.validate()
        self.log.info("config.validate() OK")

        # 2. single-instance lock (анти-задвоение ордеров).
        acquire_singleton(config.ops.LOCK_PATH)
        self.log.info("singleton-lock взят: %s", config.ops.LOCK_PATH)

        # 3. demo/mainnet домены по BYBIT_DEMO (дефолт demo).
        mode = "DEMO" if config.ops.USE_DEMO else "MAINNET"
        self.log.info("режим: %s · REST=%s", mode, config.ops.REST_URL)
        if not config.ops.USE_DEMO:
            self.log.warning("ВНИМАНИЕ: выбран MAINNET (боевой счёт)")
        if not config.ops.DATABASE_URL:                         # 5.5b: Postgres-страховка
            self.log.warning("DATABASE_URL не задан → SQLite (%s). На Railway ОБЯЗАТЕЛЬНО задай "
                             "DATABASE_URL=Postgres: иначе состояние стирается на передеплое, а дашборд "
                             "(отдельный контейнер) не видит данные воркера.", config.ops.DB_PATH)

        # 4. UTC-align (заглушка-предупреждение).
        check_utc_alignment(logger=self.log)

        # 5. брокер (инъекция для оффлайн-тестов; дефолт — реальный pybit) + маркет-данные.
        self.broker = broker if broker is not None else BybitClient()
        self.md = MarketData(self.broker, logger=self.log)
        self.symbols = [s for s, c in config.strategy.COINS_CONFIG.items() if c.get("enabled")]

        # 6. Слой данных (ф.5.2 п.1): БД + хранилища + леджер; засев из ЭФФЕКТИВНОГО конфига (крутилки,
        # не статика). db инъектируем для оффлайн-тестов; дефолт — DB(owner=True) (создаёт схему идемпотентно).
        self.db = db if db is not None else DB(owner=True)
        # 6.1 РЕСТАРТ-БЕЗОПАСНЫЙ замок «единственный воркер» (5.5a): PG advisory-lock на ОБЩЕЙ БД —
        # на Railway файловый лок (шаг 2) бесполезен (эфемерный диск per-container). Дашборд этот лок НЕ берёт.
        # При OVERLAP-передеплое Railway ЖДЁМ освобождения (5.5c), не падаем сразу (иначе дедлок).
        if not self._acquire_singleton_with_wait():
            raise SystemExit("Другой воркер держит advisory-lock БД дольше лимита — стоп, чтобы не задвоить ордера.")
        self.cfg = ConfigStore(self.db)
        self.state = StateStore(self.db)
        self.ledger = Ledger(CapitalStore(self.db))
        eff = self.cfg.effective()                              # снимок эффективных крутилок (override|дефолт)
        self.ledger.seed(eff["WORKING_START"], eff["CUSHION_START"])   # идемпотентно: повторный seed не затирает
        self.ledger.ensure_cursor_seeded(int(time.time() * 1000))     # delta-курсор compound (5a): штамп now_ms если NULL
        # 5.7-хвост «дебаунс STOP vs краш-луп»: сброс серии НА СТАРТЕ СНЯТ (было reset_stop_streak) —
        # `stop_streak` теперь ПЕРСИСТИТ через рестарт. РАННИЙ kill-switch-замер ЗДЕСЬ, ДО сетевых fail-fast
        # (ensure_one_way/reconcile/get_instruments): краш-луп, застрявший на старте при реальной −50%, всё
        # равно делает ОДИН STOP-замер на КАЖДОМ рестарте → серия растёт через рестарты → защёлкнётся (персист
        # без раннего замера — half-fix, evaluate иначе зовётся только из _poll_tick после долгого __init__).
        # fail-closed: сбой сети/None → пропуск, старт НЕ падает; evaluate(None) — no-op. Асимметрия: пропущенная
        # защёлка = новые входы в обвал; ложная = пауза, снимаемая кнопкой (дашборд жив при краше воркера).
        try:
            _kd = eff.get("KILLSWITCH_DD", config.risk.KILLSWITCH_DD)
            _ad = eff.get("ALARM_DD", config.risk.ALARM_DD)
            _was = killswitch.is_halted(self.ledger.store)             # был ли защёлкнут ДО раннего замера
            _st0 = killswitch.evaluate(self.ledger.store, killswitch.safe_equity(self.broker.get_equity_usdt()),
                                       killswitch_dd=_kd, alarm_dd=_ad)
            if killswitch.is_halted(self.ledger.store) and not _was:   # СВЕЖАЯ защёлка на старте (краш-луп) → событие монитора
                self.log.warning("СТАРТ: kill-switch ЗАЩЁЛКНУТ (краш-луп/серия ≥2 через рестарты) — торговля заблокирована до clear")
                try:                                                   # без события переход не виден в ленте (краш-луп не доживает до _poll_tick)
                    self.db.events_put(symbol="ALL", event="kill_switch_stop", detail="старт dd≥%.2f" % _kd)
                except Exception as _ev:
                    self.log.warning("events_put(kill_switch_stop, старт) пропущен: %s", _ev)
            elif killswitch.is_halted(self.ledger.store):              # защёлкнут ещё раньше (durable, событие уже было)
                self.log.warning("СТАРТ: kill-switch уже защёлкнут (durable) — торговля заблокирована до clear")
            elif _st0 == killswitch.STOP:
                self.log.warning("СТАРТ: equity на STOP-уровне (серия %s) — ещё один STOP-тик защёлкнёт рубильник",
                                 (self.ledger.store.get() or {}).get("stop_streak"))
        except Exception as _e:                                        # ранний замер best-effort — НЕ роняет старт
            self.log.warning("СТАРТ: ранний kill-switch-замер пропущен (%s)", _e)

        # Публикация env-дефолтов этого воркера (фича unified_config_source): дашборд читает снимок и показывает
        # ПРАВДУ воркера, а не свой env (env задаётся per-service — иначе показ врёт). BEST-EFFORT: сбой НЕ роняет
        # старт (показ деградирует к своему env = текущее поведение). env статичен на процесс → пишем один раз.
        try:
            self.db.worker_config_put({k: knobs.default(k) for k in knobs.KNOBS}, now_ms=int(time.time() * 1000))
        except Exception as e:
            self.log.warning("публикация worker_config не удалась (показ дашборда деградирует, не критично): %s", e)

        # bot_health: маркер старта процесса в events → дашборд считает «перезапусков за 24ч» (ловит ТИХИЙ рестарт,
        # который по свежему heartbeat не виден). Best-effort: сбой записи НЕ валит старт. ts_ms = метка старта.
        try:
            self.db.events_put(symbol="ALL", event="worker_boot", detail="старт воркера", ts_ms=self._process_start_ms)
        except Exception as e:
            self.log.warning("events_put(worker_boot) пропущен (не критично): %s", e)

        # Сводка ЭФФЕКТИВНЫХ knobs (из ConfigStore, не статика config.* — закрывает хвост 5.1).
        self.log.info(
            "knobs(eff): risk/нога=%.2f%% cap=%d shorts=%s ema=%s монет=%d режим_капитала=%s working=%.2f",
            eff["RISK_PCT_PER_LEG"], eff["CONCURRENCY_CAP"], eff["SHORTS_ENABLED"],
            eff["EMA_FILTER_ENABLED"], len(self.symbols), config.capital.CAPITAL_MODE,
            self.ledger.get()["working"],
        )

        # 7. one-way long-only на старте (ADR 0007) + сверка с биржей ОДИН раз до первого тика
        # (биржа=арбитр, рестарт-безопасность cap/состояния, ADR 0008). Стек ИСПОЛНЕНИЯ (Executor) — п.3.
        one_way = self.broker.ensure_one_way()
        if not one_way.get("ok"):                               # ЖЁСТКО (5.5a): реальная ошибка режима → СТАРТ ПРЕРВАН
            self.log.error("СТАРТ ПРЕРВАН: one-way режим НЕ подтверждён (ADR 0007, инвариант #11/#14): %s",
                           one_way.get("err"))
            raise SystemExit("one-way режим не гарантирован — стоп, чтобы не торговать против hedge-режима.")
        self.log.info("ensure_one_way: %s", one_way.get("note") or "ОК (one-way)")
        try:
            self.log.info("reconcile_on_start: %s",
                          reconcile_on_start(self.state, self.broker, self.symbols, logger=self.log))
        except Exception as e:                                  # сетевой сбой = НЕ синхронизированы -> fail-fast
            self.log.error("СТАРТ ПРЕРВАН: не удалось синхронизироваться с биржей на старте (биржа=арбитр): %s", e)
            raise                                              # понятный лог, не голый traceback (Railway видит причину)
        self._sweep_orphan_orders_open()                        # старт-sweep панели «ждущие» (5.4d): ПОСЛЕ reconcile (state=истина)
        self._backfill_timeout_on_downtime()                    # 5.7 п.6: догнать wait_postcommit за 4h простоя (ПОСЛЕ reconcile — по сверенным картам)

        # 8. Стек ИСПОЛНЕНИЯ (ф.5.2 п.3a): meta по монетам + working-провайдер + Executor (долгоживущий)
        # + биржевое плечо per coin. sizing/sl_trigger_by ПОДАЁТ цикл на старте каждого 4h-закрытия (п.3b).
        self.executor = self._build_executor(eff)
        self._ensure_stop_coverage(context="start")          # keystone-инвариант 5.7: у открытых позиций стоп ≥ net (после reconcile+executor)

        # 9. Триггер 4h-цикла (ф.5.2 п.3d): метки сканера per-coin + граница последнего цикла (in-memory;
        # на ПРОШЛУЮ 4h-границу → первый прайм-цикл сработает сразу). Персист → под-шаг 5.
        self.cursors = {s: None for s in self.symbols}
        self._last_4h_boundary = (int(time.time() * 1000) // FOUR_HOUR_MS) * FOUR_HOUR_MS - FOUR_HOUR_MS

        # account-writer (ф.5.4b): сырой ответ get_equity_usdt последнего тика (ОДИН REST кормит И kill-switch,
        # И снимок счёта) + метка последней точки кривой капитала (каденция EQHIST_INTERVAL_MS).
        self._last_eq_raw = None
        self._last_eqhist_ms = 0
        self._last_journal_ms = 0                            # троттл journal_sync (под-шаг 2); 0 (НЕ None) → без TypeError на 1-м тике

        # 10. Тёплый старт (5.8 п.3b): авто-подхват auto_eligible PENDING при WARM_ON_START. В КОНЦЕ __init__
        # (cursors/executor/state готовы). Best-effort — свой try/except внутри, сетевой сбой НЕ валит старт.
        self._maybe_warm_start()

        # 11. WS-тень (5.2 п6, measure-first): наблюдательный execution-стрим для замера края 5.6. В КОНЦЕ
        # __init__ — ПОСЛЕ advisory-lock (иначе overlap-передеплой = 2-я тень-писатель ws_exec; ADR 0014) и
        # executor (нужен prefix линка). Best-effort, дефолт OFF → self.ws_shadow=None (поведение 1:1 как без тени).
        self._maybe_start_ws_shadow()

    def _acquire_singleton_with_wait(self):
        """Взять advisory-lock «единственный воркер», ОЖИДАЯ освобождения при overlap-передеплое Railway
        (старый воркер ещё держит лок; Railway снимет его, увидев новый контейнер «живым»). True=взял;
        False=не дождались за config.ops.LOCK_WAIT_SEC (реальная коллизия — старт прервётся). Процесс при
        ожидании ЖИВ (не крэшит) — это и позволяет Railway остановить старый и освободить лок (5.5c)."""
        wait_sec = config.ops.LOCK_WAIT_SEC
        waited = 0
        while True:
            if self.db.acquire_singleton():
                if waited:
                    self.log.info("advisory-lock БД освободился и взят (ждал %dс)", waited)
                return True
            if waited >= wait_sec:
                return False
            self.log.warning("advisory-lock БД занят другим воркером — жду освобождения (%d/%dс, передеплой?)...",
                             waited, wait_sec)
            time.sleep(5)
            waited += 5

    def _build_executor(self, eff):
        """Долгоживущий стек исполнения (ф.5.2 п.3a): meta_by_symbol из get_instruments (список→дикт по
        нашим монетам, нет инструмента→WARN+skip), working-провайдер (живой), Executor + биржевое плечо
        per coin. Ордера НЕ ставит — sizing/sl_trigger_by обновляет цикл на старте каждого 4h-закрытия (п.3b)."""
        try:
            instruments = {i["symbol"]: i for i in self.broker.get_instruments()}
        except Exception as e:                                  # сетевой сбой = нет точностей инструментов -> fail-fast
            self.log.error("СТАРТ ПРЕРВАН: не удалось получить инструменты с биржи (get_instruments): %s", e)
            raise                                              # понятный лог вместо голого traceback (как reconcile выше)
        meta_by_symbol = {}
        for s in self.symbols:
            info = instruments.get(s)
            if info is None:
                self.log.warning("%s: нет в get_instruments → монета без meta (ноги пропустятся)", s)
                continue
            meta_by_symbol[s] = InstrumentMeta(info)

        self.working_provider = make_working_provider(self.ledger)
        executor = Executor(self.broker, meta_by_symbol,
                            sl_trigger_by=eff["SL_TRIGGER_BY"], logger=self.log)

        # Биржевое плечо per coin: потолок min(MAX_LEVERAGE, per-coin). set_leverage ошибку НЕ бросает
        # (часто «leverage not modified») → note в WARN. Re-set каждый цикл — хвост (риск при открытой позиции).
        for s in meta_by_symbol:
            lev = min(eff["MAX_LEVERAGE"], config.strategy.COINS_CONFIG[s]["leverage"])
            res = self.broker.set_leverage(s, lev)
            if isinstance(res, dict) and res.get("note"):
                self.log.warning("%s: set_leverage(%d) note=%s", s, lev, res["note"])

        self.log.info("стек исполнения собран: meta %d/%d монет, плечо выставлено, sl_trigger=%s",
                      len(meta_by_symbol), len(self.symbols), eff["SL_TRIGGER_BY"])
        return executor

    def on_candle(self, symbol, candle, bars):
        """ШОВ под signal -> lifecycle -> executor (фичи 3–5). Сейчас — НАМЕРЕННАЯ
        заглушка-лог: показывает, что закрытая 15m-свеча подтянута. Торговой логики нет."""
        self.log.info(
            "15m-свеча %s: t=%d close=%s (окно=%d баров)",
            symbol, candle["time"], candle["close"], len(bars),
        )

    def _maybe_start_ws_shadow(self):
        """WS-тень (5.2 п6): наблюдательный execution-стрим для замера края 5.6. Best-effort — сбой НЕ валит
        воркер (тень необязательна, торговля идёт опросом). Дефолт OFF → self.ws_shadow=None, поведение 1:1.
        Пишет ТОЛЬКО через узкий WsExecFacade (parity-safeguard); prefix линка = executor.prefix (консистентно).
        ВАЖНО (ADR 0014): зовётся в КОНЦЕ __init__, ПОСЛЕ advisory-lock — иначе overlap-передеплой поднимет 2-ю
        тень-писателя (execId-дедуп обезвредит, но лишнее соединение/пинги); не переносить раньше лока."""
        self.ws_shadow = None
        if not config.ops.WS_SHADOW_ENABLED:
            return
        try:
            from broker.ws_shadow import WsShadow
            from storage.db import WsExecFacade
            self.ws_shadow = WsShadow(
                config.ops.BYBIT_API_KEY, config.ops.BYBIT_API_SECRET, logger=self.log,
                facade=WsExecFacade(self.db), prefix=self.executor.prefix,
                exec_history=lambda s, e: self.broker.get_executions(s, e))   # REST-догон разрывов (5.2 п7)
            self.ws_shadow.start()
            try:                                            # маркер ГРАНИЦЫ ЭПОХИ тени в events → Стадия B суммирует дропы по эпохам (кросс-рестарт)
                now_ms = int(time.time() * 1000)
                self.db.events_put(symbol="ALL", event="ws_shadow_boot", detail="boot_ms=%d" % now_ms, ts_ms=now_ms)
            except Exception:
                pass
        except Exception as e:                              # best-effort — тень необязательна
            self.log.warning("WS-тень: не поднята (best-effort, торговля не затронута): %s", e)
            self.ws_shadow = None

    def _drain_ws_shadow(self):
        """Слить очередь WS-тени в ws_exec_log (5.2 п6): ГЛАВНЫЙ поток пишет пачкой — развязка от торгового
        лока (WS-поток только кладёт в очередь). Best-effort: сбой не валит тик. Инертно при OFF (ws_shadow=None)."""
        sh = getattr(self, "ws_shadow", None)
        if sh is None:
            return
        try:
            sh.drain()
        except Exception as e:
            self.log.warning("WS-тень: дренаж не удался: %s", e)

    def _heartbeat(self):
        """Пульс в БД (монитор «жив»): ts_ms + число активных сетапов + живость WS-тени (5.2 п6: ws_alive/
        last_ws_ms из наблюдателя, None-безопасно при OFF). Сбой записи не валит цикл (только лог)."""
        sh = getattr(self, "ws_shadow", None)
        try:
            st = sh.stats() if sh else None                 # снимок счётчиков тени (drops/reconnect/msgs) для Стадии B
            self.db.heartbeat_put(ts_ms=int(time.time() * 1000),
                                  active_setups=len(self.state.all()),
                                  ws_alive=bool(sh and sh.is_alive()),
                                  last_ws_ms=(sh.last_ws_ms() if sh else None),
                                  drops=(st.get("drops") if st else None),
                                  reconnect_count=(st.get("reconnect_count") if st else None),
                                  msgs_received=(st.get("msgs_received") if st else None),
                                  process_start_ms=self._process_start_ms,
                                  last_exchange_ok_ms=self._last_exchange_ok_ms)
        except Exception as e:
            self.log.warning("heartbeat в БД не записан: %s", e)

    def _poll_tick(self):
        """Один проход по монетам: новые закрытые 15m-свечи -> шов on_candle + 15m-ведение опросом
        (poll-diff fill/exit, под-шаг 4a). Снимок позиций ОДИН раз на тик (one-way нетто по монетам); сбой
        get_positions → ведение пропущено, но heartbeat и 4h-триггер живут (биржа=арбитр на след. тике).
        Ошибка по монете не валит проход; не глотаем SystemExit/KeyboardInterrupt. Пульс в БД в конце."""
        try:
            positions = self.broker.get_positions()         # ПОЛНЫЕ дикты (нужны account-writer'у), net — для ведения
            net_by_symbol = {p["symbol"]: p["size"] for p in positions}
            pos_by_symbol = {p["symbol"]: p for p in positions}   # R8-трейл: биржевая сверка соло + adopt (maybe_arm_trailer)
            self._last_exchange_ok_ms = int(time.time() * 1000)   # bot_health: Bybit ответил → «связь с биржей ок»
        except Exception as e:
            self.log.warning("15m-тик: снимок позиций не получен — ведение пропущено: %s", e)
            positions = None
            net_by_symbol = None
            pos_by_symbol = None
        now_ms = int(time.time() * 1000)
        self._mark_4h_seen(now_ms)                          # 5.7 п.6: метка-якорь backfill таймаута — ДО ведения (ВЕДЁТ счётчик → краш=недосчёт)
        self._maybe_15m_killswitch()                        # 15m-рубильник ДО ведения (docs/05 №6) + self._last_eq_raw
        self._account_snapshot(now_ms, positions)           # КЕЙСТОУН (5.4b): снимок счёта в БД — оживляет монитор
        self._maybe_flatten_all(now_ms)                     # энфорсмент «Закрыть всё» (5.3c) ДО ведения монет
        self._maybe_warm()                                  # консьюмер «Прогреть выбранные» (5.8 п.4b) ДО ведения
        try:
            _eff = self.cfg.effective()
            reanchor_v3 = bool(_eff.get("REANCHOR_AFTER_SCALP", False))   # v3-режим (override←env), fail-safe False
            runner_tp_hold = bool(_eff.get("RUNNER_TP_HOLD", False))      # фикс «живой бегунок» (ADR 0015), fail-safe False
            leg2_ext = _eff.get("LEG2_EXT")                              # цель бегунка (None → lifecycle возьмёт config-дефолт)
            dd_on = bool(_eff.get("DOUBLE_DIP_ENABLED", False))          # двойной заход 4–5% (ADR 0016, 5.9), fail-safe False
            cond05 = "double_dip" if dd_on else None                     # маппинг bool→условие входа 0.5 (движок/lifecycle считают ТЕМ ЖЕ)
            tol05 = float(_eff.get("DOUBLE_DIP_TOL", 0.04)) if dd_on else 0.0   # OFF → (None,0.0) = точное условие G0-паритета (движок :146 и так гейтит tol за cond05)
            trail_en = bool(_eff.get("TRAIL_ENABLED", False))            # R8-трейл бегунка (путь Y, Дизайн A), fail-safe OFF
            trail_r = float(_eff.get("TRAIL_R", 0.4)) if trail_en else 0.0   # OFF → 0.0 = бит-в-бит (трейлер не ставится)
        except Exception:
            reanchor_v3 = runner_tp_hold = False
            leg2_ext = None
            cond05 = None                                               # fail-safe OFF = бит-в-бит v2
            tol05 = 0.0
            trail_r = 0.0                                               # fail-safe OFF = трейлер не ставится
        for sym in self.symbols:
            try:
                candles = list(self.md.fetch_new_closed(sym))
                for candle in candles:
                    self.on_candle(sym, candle, self.md.bars.get(sym, []))
                if net_by_symbol is not None:
                    run_15m_tick(self.broker, self.state, self.executor, sym, net_by_symbol.get(sym, 0.0),
                                 self.cursors, candles, self.md.bars.get(sym, []), now_ms=now_ms, logger=self.log,
                                 reanchor_after_scalp=reanchor_v3, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                                 cond05=cond05, tol05=tol05, trail_r=trail_r, position=pos_by_symbol.get(sym))
            except Exception as e:
                self.log.warning("%s: тик пропущен (ошибка): %s", sym, e)
        self._ensure_stop_coverage(positions, context="tick")   # keystone-инвариант 5.7: не оставить позицию без стопа
        self._drain_ws_shadow()                             # WS-тень пишет очередь+REST-бэкфилл ПОСЛЕ защиты (аудит границы:
        #                                                     REST-бэкфилл в дренаже НЕ должен откладывать 15m kill-switch)
        self._maybe_journal_sync(now_ms)                    # под-шаг 2: журнал закрытых (полнота; вне money-леджера) — ПОСЛЕ
        #                                                     защитного пути (медленный closed-pnl-fetch не тормозит покрытие стопов)
        self._heartbeat()

    def _maybe_journal_sync(self, now_ms):
        """Троттл-обёртка journal_sync (под-шаг 2): не чаще JOURNAL_INTERVAL_MS (≤~96 fetch/день, щадим REST).
        Независимый писатель журнала ЗАКРЫТЫХ (дисплей-таблица `closed_trades`) — чинит задержку (15m, не 4h) и
        полноту («не все сделки»), НЕ трогая money-леджер компаунда. journal_sync сам изолирован (сбой НЕ рейзит).
        Метку двигаем ДО вызова (журнал best-effort → ретрай след. интервал; без ре-входа при частых тиках)."""
        if now_ms - self._last_journal_ms < JOURNAL_INTERVAL_MS:
            return
        self._last_journal_ms = now_ms
        journal_sync(self.broker, self.db, self.log, now_ms=now_ms)

    def _ensure_stop_coverage(self, positions=None, *, context):
        """Keystone-инвариант (5.7 п.1): у КАЖДОЙ открытой позиции с карточкой стоп ДОЛЖЕН покрывать net
        (позиционный Full stopLoss ИЛИ Σ пул -stp >= net); иначе — поставить Full-стоп по stop0 карточки
        (под LIVE-гейтом). Read-only проверка; re-arm редок. positions — снимок тика (переиспользуем, без
        лишнего REST); None → свой get_positions. Свой try/except: сбой инварианта НЕ валит тик/старт."""
        try:
            if positions is None:
                positions = self.broker.get_positions()
            pos_by_symbol = {p["symbol"]: p for p in positions}
        except Exception as e:
            self.log.warning("ensure_stop_coverage(%s): снимок позиций не получен (%s) → пропуск", context, e)
            return
        for sym in self.symbols:
            try:
                pos = pos_by_symbol.get(sym)
                if pos is None:
                    continue
                net = float(pos.get("size") or 0)
                if net <= 1e-9:
                    continue
                setup = self.state.get(sym)
                if setup is None or setup.get("stop0") is None:
                    continue                            # позиция без карточки/stop0 → сверка всего счёта (под-шаг 3)
                stop_orders = self.broker.get_open_orders(sym, order_filter="StopOrder")
                stp_qty = protection.sum_stop_qty(stop_orders, self.executor.prefix, sym)
                if protection.is_covered(net, pos.get("stop_loss"), stp_qty):
                    continue
                stop0 = setup["stop0"]
                self.log.warning("ensure_stop_coverage(%s): %s net=%.10g БЕЗ покрытия стопом "
                                 "(Full=%s Σ-stp=%.10g) → ставлю Full=%s", context, sym, net,
                                 pos.get("stop_loss"), stp_qty, stop0)
                if not config.ops.LIVE_TRADING_ENABLED:
                    self.log.warning("ensure_stop_coverage(%s): %s LIVE off — стоп НЕ поставлен (dry-run)", context, sym)
                    continue
                meta = self.executor.meta.get(sym)
                if meta is None:                        # без точностей инструмента округлить нечем → как под-шаг 3
                    self.log.warning("ensure_stop_coverage(%s): %s без InstrumentMeta → стоп НЕ поставлен", context, sym)
                    continue
                stop_str = meta.price_str(meta.fix_price(stop0))   # округление под тик (как executor.py:121) — иначе Bybit отвергнет
                self.broker.set_trading_stop(sym, stop_loss=stop_str, position_idx=0,
                                             sl_trigger_by=self.executor.sl_trigger_by)
            except Exception as e:
                self.log.warning("ensure_stop_coverage(%s): %s пропущен (%s)", context, sym, e)

    def _maybe_15m_killswitch(self):
        """15m-контур kill-switch (ИНВАРИАНТ docs/05 №6): портфельный замер просадки КАЖДЫЙ тик (один
        get_equity_usdt) + при STOP-защёлке отмена НЕЗАЛИТЫХ ног — внутри-4h обвал не должен опаздывать.
        fail-closed: eq=None → evaluate no-op, латч держится. Отмена уважает LIVE_TRADING_ENABLED (у
        cancel_all_legs своего гейта НЕТ). Свой try/except — сбой НЕ валит остальной тик/heartbeat.
        Сохраняет СЫРОЙ ответ get_equity_usdt в self._last_eq_raw — ТОТ ЖЕ REST кормит account-writer (5.4b),
        консистентно с латчем; сбой/None → fail-open в _account_snapshot не пишет (анти-фантом-STOP)."""
        self._last_eq_raw = None
        try:
            try:
                eff = self.cfg.effective(strict=True)
                kill_dd, alarm_dd = eff["KILLSWITCH_DD"], eff["ALARM_DD"]
            except Exception as e:                          # порча конфига → статик-дефолты (рубильник всё равно жив)
                kill_dd, alarm_dd = config.risk.KILLSWITCH_DD, config.risk.ALARM_DD
                self.log.warning("15m kill-switch: конфиг невалиден (%s) → статик-пороги DD %.2f/%.2f",
                                 e, kill_dd, alarm_dd)
            raw = self.broker.get_equity_usdt()             # ОДИН REST: кормит И защёлку, И account-writer (5.4b)
            self._last_eq_raw = raw
            eq = killswitch.safe_equity(raw)
            was_halted = killswitch.is_halted(self.ledger.store)
            killswitch.evaluate(self.ledger.store, eq, killswitch_dd=kill_dd, alarm_dd=alarm_dd)  # eq=None → no-op
            if killswitch.is_halted(self.ledger.store) and not was_halted:   # переход в STOP → событие монитора (раз, 5.4c)
                try:
                    self.db.events_put(symbol="ALL", event="kill_switch_stop", detail="dd≥%.2f" % kill_dd)
                except Exception as ev:
                    self.log.warning("events_put(kill_switch_stop) пропущен: %s", ev)
            if not killswitch.is_halted(self.ledger.store):
                return
            if not config.ops.LIVE_TRADING_ENABLED:
                self.log.warning("15m kill-switch STOP: [DRY-RUN] отменил БЫ незалитые ноги (LIVE_TRADING_ENABLED=0)")
                return
            n = 0                                           # отменить незалитые (PENDING) ноги — только сетапы, где они ЕСТЬ
            for sym, setup in self.state.all().items():
                if not any(leg.get("state") == PENDING for leg in setup["legs"].values()):
                    continue                                # нет незалитых ног → нечего отменять (без write-амплификации)
                self.executor.cancel_all_legs(sym, setup)
                self.state.put(sym, setup)                  # персист отмены (link_id/order_id сняты)
                try:
                    # панель «ждущие»: PENDING сняты → строку убрать (5.4d). Belt-and-suspenders к само-чистке
                    # writer'а (run_15m_tick этот же тик увидит link=None → сам снимет) — НЕ удалять одно из двух.
                    self.db.orders_open_clear(sym)
                except Exception as oc:
                    self.log.warning("orders_open_clear(%s) пропущен: %s", sym, oc)
                n += 1
            if n:
                self.log.warning("15m kill-switch STOP активен → незалитые ноги отменены (%d сетапов)", n)
        except Exception as e:
            self.log.warning("15m kill-switch: пропуск (ошибка): %s", e)

    def _account_snapshot(self, now_ms, positions):
        """КЕЙСТОУН монитора (5.4b): снимок счёта в БД (`account_put`) + точка кривой капитала (`equity_history_put`
        по каденции EQHIST_INTERVAL_MS). Берёт equity ИЗ ТОГО ЖЕ get_equity_usdt, что и kill-switch
        (`self._last_eq_raw`) — один REST, консистентно с латчем. **FAIL-OPEN:** пишем ТОЛЬКО при валидной equity
        (`safe_equity(raw) is not None`, тот же предикат, что у evaluate) — NULL-equity включила бы фантом-STOP на
        дашборде (live=True, equity→0 → dd≈100%). Снимок позиций упал (positions=None) → equity-only, positions=[]
        (equity_live важнее позиций). positions: snake_case брокера → camelCase фронта (cockpit.js). observability —
        вне LIVE_TRADING_ENABLED (читаем, не ставим). Свой try/except — сбой записи НЕ валит тик."""
        try:
            eq = killswitch.safe_equity(self._last_eq_raw)
            if eq is None:                                  # {err}/total_equity None → НЕ пишем (анти-фантом-STOP)
                return
            raw = self._last_eq_raw
            usdt = raw.get("usdt_equity") if isinstance(raw, dict) else None
            pos = []
            for p in (positions or []):                     # snake_case → camelCase, как читает cockpit.js
                if isinstance(p, dict) and p.get("symbol"):
                    pos.append({"symbol": p.get("symbol"), "side": p.get("side"), "size": p.get("size"),
                                "avgPrice": p.get("avg_price"), "markPrice": p.get("mark_price"),
                                "unrealisedPnl": p.get("unrealised_pnl"), "leverage": p.get("leverage")})
            self.db.account_put(total_equity=eq, usdt_equity=usdt, positions=pos)
            if now_ms - self._last_eqhist_ms >= config.ops.EQHIST_INTERVAL_MS:   # каденция кривой (рост таблицы ограничен)
                self.db.equity_history_put(ts_ms=now_ms, total_equity=eq)
                self._last_eqhist_ms = now_ms
        except Exception as e:
            self.log.warning("account-snapshot: пропуск (ошибка): %s", e)

    def _sweep_orphan_orders_open(self):
        """Старт-sweep панели «ждущие» (5.4d): снять orders_open-строки по символам БЕЗ активной карточки
        (фантомы прошлых путей/рестартов — writer не был подключён ранее). ЗАВИСИТ от порядка: зовётся ПОСЛЕ
        reconcile_on_start (state.all уже авторитетен). Свой try/except — сбой НЕ валит старт воркера."""
        try:
            active = set(self.state.all().keys())
            for row in self.db.orders_open_all():
                sym = row.get("symbol")
                if sym and sym not in active:
                    self.db.orders_open_clear(sym)
                    self.log.info("старт-sweep: снят фантом панели «ждущие» %s (нет активной карточки)", sym)
        except Exception as e:
            self.log.warning("старт-sweep orders_open: пропуск (ошибка): %s", e)

    def _mark_4h_seen(self, now_ms):
        """5.7 п.6: штамп метки-якоря `last_4h_seen_ms` = текущая 4h-граница, когда она продвинулась. Зовётся
        в НАЧАЛЕ _poll_tick (ДО ведения, где инкрементится wait_postcommit) → метка ВЕДЁТ счётчик → любой краш
        даёт НЕДОСЧЁТ (таймаут максимум на 4h позже — безопасно), НИКОГДА пере-счёт (ранний ложный выход).
        Продвигается независимо от наличия сетапов → нет пере-счёта для сетапа, созданного после простоя."""
        cb = (now_ms // FOUR_HOUR_MS) * FOUR_HOUR_MS
        try:
            seen = self.ledger.store.get_last_4h_seen()
            if seen is None or cb > int(seen):
                self.ledger.store.set_last_4h_seen(cb)
        except Exception as e:
            self.log.warning("5.7 п.6: штамп метки 4h не удался (не критично): %s", e)

    def _backfill_timeout_on_downtime(self, now_ms=None):
        """5.7 п.6: на старте догнать `wait_postcommit` committed-сетапов за 4h-границы, пропущенные в простое.
        В простое тика нет → `fetch_new_closed` праймит без эмиссии → счётчик заморожен → backfill ЕДИНСТВЕННЫЙ
        догоняющий (двойного счёта из тика нет). `missed = (текущая − метка)/4h`, cap TIMEOUT_BARS. БЕЗОПАСНЫЙ
        ПОРЯДОК: метку=текущая пишем ПЕРВОЙ, потом advance → краш посередине даёт недосчёт (повтор не задваивает),
        не пере-счёт. Метка NULL (первый запуск фичи / сброс БД) → fail-safe skip + WARN (форс-таймаут на пустой
        БД закрыл бы здоровые позиции). Свой try/except — сбой НЕ валит старт. Зовётся ПОСЛЕ reconcile_on_start.
        now_ms — инъекция для теста (дефолт wall-clock)."""
        try:
            cap = int(config.execution.TIMEOUT_BARS)
            now = int(time.time() * 1000) if now_ms is None else int(now_ms)
            cb = (now // FOUR_HOUR_MS) * FOUR_HOUR_MS
            seen = self.ledger.store.get_last_4h_seen()
            if seen is None:                                     # первый запуск фичи / сброс БД → missed неизвестен
                self.ledger.store.set_last_4h_seen(cb)          # засеять метку (со следующего простоя backfill заработает)
                self.log.warning("5.7 п.6: backfill таймаута ПРОПУЩЕН — метка 4h не персистирована (первый запуск "
                                 "фичи / сброс БД). Счётчики committed-сетапов НЕ подтянуты за простой; если есть "
                                 "старые позиции — сверь working/таймаут вручную.")
                return
            seen = (int(seen) // FOUR_HOUR_MS) * FOUR_HOUR_MS   # defensive: выровнять под 4h-сетку (битая/дробная запись)
            missed = max(0, min(cap, (cb - seen) // FOUR_HOUR_MS))
            self.ledger.store.set_last_4h_seen(cb)              # МЕТКУ ПЕРВОЙ (safe order: краш посередине → недосчёт, не пере-счёт)
            if missed == 0:
                return
            bumped = 0
            for sym, setup in self.state.all().items():
                if not setup.get("committed"):                  # не-committed: wait_postcommit и вживую не тикает
                    continue
                wp0 = int(setup.get("wait_postcommit", 0) or 0)
                wp1 = min(cap, wp0 + missed)
                if wp1 != wp0:
                    setup["wait_postcommit"] = wp1
                    self.state.put(sym, setup)
                    bumped += 1
            if bumped:
                self.log.warning("5.7 п.6: простой ~%d×4h → wait_postcommit подтянут у %d committed-сетапов "
                                 "(cap %d); просроченные закроются по таймауту на 1-м тике.", missed, bumped, cap)
        except Exception as e:
            self.log.warning("5.7 п.6: backfill таймаута не выполнен (не критично, старт продолжается): %s", e)

    def _maybe_flatten_all(self, now_ms):
        """Энфорсмент «Закрыть всё» (5.3c): при новом durable-намерении закрыть ВСЕ активные сетапы + авто-пауза.
        Свой try/except — сбой НЕ валит остальной тик/heartbeat. Логика/идемпотентность — в cycle.maybe_flatten_all."""
        try:
            maybe_flatten_all(self.db, self.state, self.executor, self.cfg, self.ledger,
                              self.cursors, now_ms=now_ms, logger=self.log)
        except Exception as e:
            self.log.warning("CLOSE_ALL flatten: пропуск (ошибка): %s", e)

    def _maybe_warm(self):
        """Консьюмер кнопки «Прогреть выбранные» (5.8 п.4b): при новом durable-намерении WARM_APPLY греет
        одобренные оператором монеты (PENDING). Свой try/except — сбой НЕ валит тик. Логика/идемпотентность/
        гейты — в cycle.maybe_warm. Зовётся каждый 15m-тик рядом с _maybe_flatten_all."""
        try:
            maybe_warm(self.broker, self.state, self.cfg, self.ledger, self.executor,
                       self.working_provider, self.symbols, self.cursors, logger=self.log)
        except Exception as e:
            self.log.warning("WARM_APPLY: пропуск (ошибка): %s", e)

    def _maybe_warm_start(self):
        """Тёплый старт (5.8 п.3b, ADR 0013): при WARM_ON_START авто-подхват auto_eligible PENDING на старте.
        Best-effort: свой try/except — сетевой сбой warm НЕ валит старт воркера (как reconcile-соседи).
        Гейты/постановка/cap — в cycle.warm_start_auto (WARM_ON_START-гейт первым → дефолт OFF = чистый no-op)."""
        try:
            warm_start_auto(self.broker, self.state, self.cfg, self.ledger, self.executor,
                            self.working_provider, self.symbols, self.cursors, logger=self.log)
        except Exception as e:
            self.log.warning("warm-старт: пропуск (ошибка): %s", e)

    def _maybe_4h_cycle(self, now_ms):
        """Раз на 4h-границу UTC (по часам, не по свече → нет 0×/10×): торговый цикл. _last_4h_boundary
        in-memory (сброс на рестарте = no-backfill). Зовётся ПОСЛЕ 15m-тика. Сбой цикла не валит воркер."""
        b4 = (now_ms // FOUR_HOUR_MS) * FOUR_HOUR_MS
        if b4 <= self._last_4h_boundary:
            return
        self._last_4h_boundary = b4
        try:
            run_4h_cycle(self.broker, self.state, self.cfg, self.ledger, self.executor,
                         self.working_provider, self.symbols, self.cursors, logger=self.log)
        except Exception as e:
            self.log.error("4h-цикл упал (не валим воркер): %s", e)
        self._write_warm_candidates()                       # снимок warm-кандидатов для превью дашборда (5.8 п.4a)
        self._write_scan_snapshot(now_ms)                   # снимок 4h-скана (bot_health 2b) — карточка «Здоровье и работа»

    def _write_warm_candidates(self):
        """Снимок warm-кандидатов в БД на 4h-границе (5.8 п.4a) — превью дашборда (под-шаг 5). Свой try/except:
        снимок best-effort (только чтение+запись, без ордеров) — сбой НЕ валит 4h-путь/воркер."""
        try:
            write_warm_candidates(self.broker, self.state, self.cfg, self.symbols, logger=self.log)
        except Exception as e:
            self.log.warning("снимок warm-кандидатов: пропуск (ошибка): %s", e)

    def _write_scan_snapshot(self, now_ms):
        """Снимок последнего 4h-скана в БД (bot_health 2b) — карточка «Здоровье и работа бота» (под-шаг 3).
        Best-effort: только чтение (зонд+детектор, без ордеров) — сбой НЕ валит 4h-путь/воркер."""
        try:
            write_scan_snapshot(self.broker, self.state, self.cfg, self.symbols, now_ms=now_ms, logger=self.log)
        except Exception as e:
            self.log.warning("снимок скана: пропуск (ошибка): %s", e)

    def run(self, once=False):
        self.log.info(
            "15m-планировщик поднят: монет %d, интервал %sм, буфер +%dс.",
            len(self.symbols), config.ops.EXEC_INTERVAL, self.BOUNDARY_BUFFER_SEC,
        )
        if once:
            self._poll_tick()
            self._maybe_4h_cycle(int(time.time() * 1000))      # смоук: прогнать 4h-цикл (прайм)
            self.log.info("--once: один тик выполнен, выходим (0).")
            return 0

        step_ms = interval_ms()
        last_heartbeat = 0.0
        while True:
            now_ms = int(time.time() * 1000)
            next_b = next_boundary_ms(now_ms, step_ms)
            # сон до границы 15m + буфер; кусками <= HEARTBEAT_SEC, чтобы heartbeat жил.
            sleep_s = max(1.0, (next_b - now_ms) / 1000.0 + self.BOUNDARY_BUFFER_SEC)
            if time.time() - last_heartbeat >= config.ops.HEARTBEAT_SEC:
                self.log.info("heartbeat: монет %d, до 15m-границы ~%dс", len(self.symbols), int(sleep_s))
                self._heartbeat()                              # пульс в БД и между тиками (монитор не «протухнет»)
                last_heartbeat = time.time()
            time.sleep(min(sleep_s, config.ops.HEARTBEAT_SEC))
            if int(time.time() * 1000) >= next_b:
                self._poll_tick()
                self._maybe_4h_cycle(int(time.time() * 1000))  # на 4h-границе (по часам) — торговый цикл


def main():
    once = "--once" in sys.argv
    app = PifagorApp()
    try:
        return app.run(once=once)
    finally:
        sh = getattr(app, "ws_shadow", None)
        if sh is not None:
            try:                        # ФИНАЛЬНЫЙ снимок счётчиков эпохи в events для Стадии B (граничный дроп-хвост; SIGKILL его теряет — ADR: drops=нижняя граница)
                st = sh.stats()
                app.db.events_put(symbol="ALL", event="ws_shadow_stop", ts_ms=int(time.time() * 1000),   # ts_ms: симметрия с boot, привязка к оси ws_gaps
                                  detail="drops=%s reconnect=%s msgs=%s" % (
                                      st.get("drops"), st.get("reconnect_count"), st.get("msgs_received")))
            except Exception:
                pass
            try:
                sh.stop()               # закрыть WS-тень ПЕРЕД БД (5.2 п6; daemon-поток страхует при SIGKILL)
            except Exception:
                pass
        app.db.close()                  # снять advisory-lock/закрыть соединение на штатном выходе (5.5a)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        sys.exit(0)
