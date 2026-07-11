# -*- coding: utf-8 -*-
"""storage.db — слой хранилища: single-instance lock + dual-engine БД (PG/SQLite).

- Файловый single-instance lock (acquire_singleton, модульный): точка входа берёт его ДО любой
  работы, чтобы rolling-деплой Railway не задвоил инстансы (как в скелете, Веха 1).
- DB: единый интерфейс к Postgres (Railway) или SQLite (локально), движок по config.ops.DATABASE_URL
  (postgres:// → PG, иначе SQLite в config.ops.DB_PATH). Таблицы: setup_state
  (снимок карточек сетапов, переживает рестарт; ADR 0008) + capital_state (леджер working/cushion,
  peak, защёлки kill-switch; Веха 4 фича 1, ADR 0010) + config_state/config_log (рантайм-крутилки +
  журнал изменений; Веха 4 фича 2, docs/14 §3–4) + логовые таблицы дашборда signals/fills/events/
  heartbeat/orders_open/account/equity_history (Веха 4 ф.3 — дашборд ЧИТАЕТ; ПИШЕТ движок, Веха 5).
- DB.acquire_singleton (advisory-lock PG / файловый SQLite) защищает мульти-контейнерный деплой;
  проводку в старт делает интеграция (Веха 5).
"""
import fcntl
import json
import os
import threading
from datetime import datetime, timezone

import config
from logging_.trade_logger import get_logger

_lock_handle = None  # держим файл открытым на всё время жизни процесса


def acquire_singleton(lock_path):
    """Взять эксклюзивный файловый лок. Если занят — другой экземпляр уже работает,
    выходим чисто (SystemExit), не трогая биржу."""
    global _lock_handle
    directory = os.path.dirname(os.path.abspath(lock_path))
    os.makedirs(directory, exist_ok=True)

    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit(
            f"Другой экземпляр уже запущен (lock занят: {lock_path}). "
            "Останавливаюсь, чтобы не задвоить ордера."
        )
    handle.write(str(os.getpid()))
    handle.flush()
    _lock_handle = handle
    return handle


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


# Схемы без serial/autoincrement -> ОДНА схема для PG и SQLite (id пишем явно, как раньше для setup_state).
# capital_state — единственная строка леджера (id=1): working/cushion/ratio (база сайзинга),
# peak_equity (HWM для kill-switch), защёлки killswitch_active/alarm_active, бухгалтерия рефинанса
# last_refinance_ts/last_refinance_total (расширение сверх docs/14 §4 — ADR 0010, doc-sync под-шаг 5).
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS setup_state(
        symbol TEXT PRIMARY KEY, payload TEXT, updated_ts TEXT)""",
    """CREATE TABLE IF NOT EXISTS capital_state(
        id INTEGER PRIMARY KEY, working REAL, cushion REAL, ratio REAL,
        peak_equity REAL, killswitch_active INTEGER, alarm_active INTEGER,
        last_refinance_ts TEXT, last_refinance_total REAL,
        last_closed_ms BIGINT, last_closed_ids TEXT, close_all_ack_id BIGINT, stop_streak INTEGER, idle_gap_ms BIGINT, last_4h_seen_ms BIGINT, warm_ack_id BIGINT, updated_ts TEXT)""",
    # config_state — текущие АКТИВНЫЕ значения 🎛-крутилок (key-value, TEXT-значение, парс — ConfigStore).
    """CREATE TABLE IF NOT EXISTS config_state(
        key TEXT PRIMARY KEY, value TEXT, updated_ts TEXT)""",
    # config_log — append-only журнал изменений (docs/14 §3); id без SERIAL (MAX+1 под локом, dual-engine).
    """CREATE TABLE IF NOT EXISTS config_log(
        id INTEGER PRIMARY KEY, ts TEXT, param TEXT, old TEXT, new TEXT,
        source TEXT, applied_from_bar INTEGER)""",
    # ── Логовые таблицы дашборда (Веха 4 ф.3): дашборд ЧИТАЕТ; ПИШЕТ движок (Веха 5). Зеркало
    # legacy_bot_reference/db.py: BIGSERIAL -> id INTEGER PRIMARY KEY (MAX+1 у писателя, как config_log);
    # ms-метки (ts_ms/bar_time/last_ws_ms) -> BIGINT (dual-engine, без overflow PG int32).
    """CREATE TABLE IF NOT EXISTS signals(
        id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, side TEXT, bar_time BIGINT,
        min_bar_pct REAL, a REAL, b REAL, entry_0382 REAL, entry_05 REAL, entry_0618 REAL,
        stop REAL, tgt_0382 REAL, tgt_05 REAL, tgt_0618 REAL,
        shadow_would_touch TEXT, shadow_same_bar TEXT, shadow_outcome TEXT, shadow_ret_pct REAL)""",
    # detect_bar_ms/order_id (5.2 п6): знаменатель замера края WS — граница 15m ОБНАРУЖЕНИЯ залива опросом
    # (не wall-clock) + orderId для сверки с ws_exec_log.order_id (лаг = detect_bar_ms − exec_time_ms).
    """CREATE TABLE IF NOT EXISTS fills(
        id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, side TEXT, entry_level TEXT,
        order_link_id TEXT, requested_price REAL, exec_price REAL, slip_pct REAL,
        requested_qty REAL, exec_qty REAL, partial TEXT, exec_fee REAL, fee_rate REAL,
        exec_type TEXT, balance_used REAL, risk_pct REAL, stop_distance_pct REAL,
        nominal_usd REAL, leverage_eff REAL, same_bar_flag TEXT, filled_pre_rebuild TEXT,
        detect_bar_ms BIGINT, order_id TEXT)""",
    # ts_ms (5.2 п6): для leg_exit — граница 15m обнаружения ВЫХОДА опросом (край выходов сверяем с WS).
    # exit_link/order_id/lv/role/qty (ws_stage_b_preconditions): СТРУКТУРНЫЙ ключ выхода для офлайн-сверки
    # края Стадии B (leg_exit; прочие события NULL). exit_link = orderLinkId, под которым WS-исполнение выхода
    # (пул -tgt/-stp для rule A; ВХОДНОЙ -ent для embedded-Full rule B). Аддитивно, старые строки NULL.
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, event TEXT, detail TEXT, ts_ms BIGINT,
        exit_link TEXT, order_id TEXT, lv REAL, role TEXT, qty REAL)""",
    # drops/reconnect_count/msgs_received (ws_stage_b_preconditions): ТЕКУЩИЙ снимок счётчиков WS-тени
    # (наблюдаемость + Стадия B). NULL при OFF/до-тени. Границы эпох (рестарт) — маркеры ws_shadow_boot/stop в events.
    # process_start_ms/last_exchange_ok_ms (bot_health): метка старта процесса (→ аптайм/«проснулся») + время
    # последнего успешного вызова Bybit (→ честный индикатор «связь с биржей», отдельный от heartbeat=тик жив).
    """CREATE TABLE IF NOT EXISTS heartbeat(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, active_setups INTEGER,
        ws_alive TEXT, last_ws_ms BIGINT, note TEXT,
        drops BIGINT, reconnect_count BIGINT, msgs_received BIGINT,
        process_start_ms BIGINT, last_exchange_ok_ms BIGINT)""",
    """CREATE TABLE IF NOT EXISTS orders_open(
        symbol TEXT PRIMARY KEY, ts TEXT, payload TEXT)""",
    # warm_candidates — снимок ТЕКУЩИХ кандидатов тёплого старта (per-symbol upsert, как orders_open): дашборд
    # ЧИТАЕТ (превью под-шаг 5), воркер ПИШЕТ на 4h-границе (Веха 5.8 п.4a). payload = дескриптор warm.classify.
    """CREATE TABLE IF NOT EXISTS warm_candidates(
        symbol TEXT PRIMARY KEY, ts TEXT, payload TEXT)""",
    # scan_snapshot — снимок ПОСЛЕДНЕГО 4h-скана (одна строка id=1, upsert): сколько монет/сигналов + список
    # греющихся кандидатов (bot_health под-шаг 2b). Воркер ПИШЕТ на 4h-границе, дашборд ЧИТАЕТ (под-шаг 3).
    """CREATE TABLE IF NOT EXISTS scan_snapshot(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, coins_scanned INTEGER,
        signals_found INTEGER, payload TEXT)""",
    # worker_config — снимок env-ДЕФОЛТОВ воркера (единый источник ПОКАЗА конфига на дашборде, фича
    # unified_config_source): воркер ПИШЕТ на старте (env статичен на процесс), дашборд ЧИТАЕТ и резолвит
    # override(config_state, ОБЩИЙ) ← этот дефолт ← свой env. defaults = JSON {knob: value}. Single-row id=1.
    """CREATE TABLE IF NOT EXISTS worker_config(
        id INTEGER PRIMARY KEY, ts TEXT, defaults TEXT, updated_ms BIGINT)""",
    """CREATE TABLE IF NOT EXISTS account(
        id INTEGER PRIMARY KEY, ts TEXT, total_equity REAL, usdt_equity REAL,
        realised_pnl REAL, closed_trades INTEGER, positions TEXT)""",
    """CREATE TABLE IF NOT EXISTS equity_history(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, total_equity REAL,
        realised_pnl REAL, closed_trades INTEGER)""",
    # closed_trades — журнал ЗАКРЫТЫХ сделок с ЧЕСТНЫМ per-trade P&L (trade_history_pnl): воркер до-сохраняет
    # реальные строки Bybit closed-pnl (symbol/side/qty/avg_entry/avg_exit/closed_pnl), уже тянутые для компаунда
    # (app/cycle._compound_realized) — дашборд ЧИТАЕТ и рисует «Историю». Дашборд БЕЗ ключей → сам биржу не
    # спросит (граница безопасности), источник P&L ТОЛЬКО воркер. dedup_key = ПОЛНАЯ идентичность строки
    # (created_ms|order_id|closed_pnl|qty|…) — идемпотентность к ре-поллу ПОСЛЕ краха (байт-идентичные строки),
    # но БЕЗ схлопывания РАЗНЫХ строк одного ордера: компаунд суммирует closed-pnl как МУЛЬТИМНОЖЕСТВО (orderId
    # НЕ уникален на строку — bybit_client.py:186), журнал обязан хранить те же строки, иначе сумма P&L разойдётся
    # с working. created_ms BIGINT (dual-engine, ось сортировки).
    """CREATE TABLE IF NOT EXISTS closed_trades(
        id INTEGER PRIMARY KEY, ts TEXT, created_ms BIGINT, symbol TEXT, side TEXT,
        qty REAL, avg_entry REAL, avg_exit REAL, closed_pnl REAL, order_id TEXT, dedup_key TEXT)""",
    # ── WS-тень (Веха 5.2 п6, measure-first): ws_exec_log — реальные execution-события приватного стрима
    # для замера края Вехи 5.6 (лаг опроса + slip). exec_id UNIQUE — идемпотентный ключ дедупа (глобально
    # уникален у Bybit; НЕ (link_id, time) — иначе партиалы склеятся, reconnect-дубли пройдут). Тень пишет
    # через узкий WsExecFacade вне пути решений (ADR 0014 — планируется, под-шаг 7). ws_gaps — окна разрыва WS.
    """CREATE TABLE IF NOT EXISTS ws_exec_log(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, symbol TEXT,
        order_link_id TEXT, order_id TEXT, exec_id TEXT UNIQUE, side TEXT,
        exec_price REAL, exec_qty REAL, exec_time_ms BIGINT, exec_type TEXT, exec_fee REAL,
        is_foreign INTEGER DEFAULT 0, is_backfilled INTEGER DEFAULT 0, raw TEXT)""",
    """CREATE TABLE IF NOT EXISTS ws_gaps(
        id INTEGER PRIMARY KEY, ts TEXT, gap_start_ms BIGINT, gap_end_ms BIGINT, backfilled INTEGER DEFAULT 0)""",
    # ── Сканер-разведчик (Веха 7, advisory scout): keyless-сервис pifagor-scout ПИШЕТ, дашборд ЧИТАЕТ.
    # scout_universe — вся просканированная вселенная Этапа A (per-symbol upsert: метрики состоятельности + скор +
    # причины отсева, включая ОТСЕЯННЫЕ — честная воронка). scout_meta — снимок последнего прогона (воронка/
    # тайминги/расписание, single-row id=1). Скаут НЕ трогает боевые таблицы; свой лок ≠918273 (не берёт вообще).
    """CREATE TABLE IF NOT EXISTS scout_universe(
        symbol TEXT PRIMARY KEY, ts TEXT, ts_ms BIGINT, score REAL, payload TEXT)""",
    """CREATE TABLE IF NOT EXISTS scout_meta(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, payload TEXT)""",
    # scout_list — курированный СПИСОК (топ-N по скору + пол, с барами mb1/mb2 и их источником config|volnorm-v1);
    # источник вселенной Этапа B (под-шаг 2). Snapshot-семантика: выпавшие символы удаляются (put_snapshot).
    """CREATE TABLE IF NOT EXISTS scout_list(
        symbol TEXT PRIMARY KEY, ts TEXT, ts_ms BIGINT, score REAL,
        mb1 REAL, mb2 REAL, bar_source TEXT, payload TEXT)""",
    # scout_klines — ROLLING кэш свечей (под-шаг 2b, решение владельца 2026-07-08): скан(3)/график(5b) читают
    # ОТСЮДА, не с биржи. PK (symbol,tf,time_ms) → идемпотентный докач (перекрытие не дублит). Ретеншн ~1000
    # баров/ТФ (прунинг) ≈ десятки МБ. Скаут ПИШЕТ, дашборд ЧИТАЕТ. tf — имя ('4h'/'1h'), не Bybit-код.
    """CREATE TABLE IF NOT EXISTS scout_klines(
        symbol TEXT, tf TEXT, time_ms BIGINT,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        PRIMARY KEY(symbol, tf, time_ms))""",
    # scout_findings — снимок ПОСЛЕДНЕГО скана Этапа B (per-symbol upsert + snapshot-удаление выпавших): ТРИ
    # статуса (forming|tracking|ready) + уровни/дистанции. scout_findings_log — append-журнал
    # «что советовал» для пост-анализа (решение §O.8: строим сразу). Скаут ПИШЕТ, дашборд ЧИТАЕТ (под-шаг 5).
    """CREATE TABLE IF NOT EXISTS scout_findings(
        symbol TEXT, ts TEXT, ts_ms BIGINT, status TEXT, tf TEXT, score REAL, payload TEXT,
        PRIMARY KEY(symbol, tf))""",
    """CREATE TABLE IF NOT EXISTS scout_findings_log(
        id INTEGER PRIMARY KEY, ts TEXT, ts_ms BIGINT, symbol TEXT, status TEXT, payload TEXT)""",
    # scout_selections — закладки владельца (под-шаг 6): symbol PK + СНИМОК точных уровней на момент выбора
    # (payload = находка целиком: entries/stop/B/status). Дашборд пишет (auth+CSRF), читает и считает свежесть
    # (снимок vs текущая находка). Фаза 1 — личная пометка, НЕ действие бота (боевая «дверь» с control — Фаза 2).
    """CREATE TABLE IF NOT EXISTS scout_selections(
        symbol TEXT PRIMARY KEY, ts TEXT, ts_ms BIGINT, payload TEXT)""",
    # scout_control — управление сервисом-скаутом (под-шаг 4): durable-намерение кнопки «Сканировать сейчас»
    # (scan_now_ms/ack, single-shot) + метки последних прогонов (last_a/last_b_boundary) + heartbeat. Дашборд
    # пишет ТОЛЬКО scan_now_ms (кнопка), скаут — ack/last_*/heartbeat (targeted UPDATE, без клоббера). id=1.
    """CREATE TABLE IF NOT EXISTS scout_control(
        id INTEGER PRIMARY KEY, scan_now_ms BIGINT, scan_now_ack_ms BIGINT,
        last_a_ms BIGINT, last_b_boundary_ms BIGINT, heartbeat_ms BIGINT, updated_ts TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_scout_universe_score ON scout_universe(score)",   # ORDER BY score DESC (топ-N)
    "CREATE INDEX IF NOT EXISTS idx_scout_list_score ON scout_list(score)",
    "CREATE INDEX IF NOT EXISTS idx_scout_klines_sym_tf_ts ON scout_klines(symbol, tf, time_ms)",
    "CREATE INDEX IF NOT EXISTS idx_eqhist_ts ON equity_history(ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_signals_sym_ts ON signals(symbol, ts)",
    "CREATE INDEX IF NOT EXISTS idx_fills_sym_ts ON fills(symbol, ts)",
    "CREATE INDEX IF NOT EXISTS idx_events_sym_ts ON events(symbol, ts)",
    "CREATE INDEX IF NOT EXISTS idx_hb_ts ON heartbeat(ts_ms)",
    "CREATE INDEX IF NOT EXISTS idx_wsexec_link ON ws_exec_log(order_link_id)",
    "CREATE INDEX IF NOT EXISTS idx_wsexec_ts ON ws_exec_log(exec_time_ms)",
    "CREATE INDEX IF NOT EXISTS idx_ws_gaps_start ON ws_gaps(gap_start_ms)",   # джойн окон бэкфилла в ws_edge_report (аудит A)
    # UNIQUE(dedup_key) — идемпотентный ключ closed_trades (ON CONFLICT DO NOTHING). dedup_key — ОДНА строка
    # (не композит) → NULL order_id безопасен (в ключе → "None", а не distinct-NULL, который выключил бы дедуп).
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_closed_trades_dedup ON closed_trades(dedup_key)",
    "CREATE INDEX IF NOT EXISTS idx_closed_trades_created ON closed_trades(created_ms)",   # ORDER BY created_ms DESC (read)
]

# Колонки леджера (без id/updated_ts — их ведёт слой БД). Единый источник порядка для put/mutate.
# ВАЖНО: capital_mutate пишет ТОЛЬКО эти колонки — новая колонка без записи сюда молча НЕ персистится.
CAPITAL_COLS = ("working", "cushion", "ratio", "peak_equity",
                "killswitch_active", "alarm_active",
                "last_refinance_ts", "last_refinance_total",
                "last_closed_ms", "last_closed_ids", "close_all_ack_id", "stop_streak", "idle_gap_ms",
                "last_4h_seen_ms", "warm_ack_id")

# Колонки ws_exec_log (без id — его ведёт слой БД: MAX+1 один раз на батч). Порядок для ws_exec_put_many.
WS_EXEC_COLS = ("ts", "ts_ms", "symbol", "order_link_id", "order_id", "exec_id", "side",
                "exec_price", "exec_qty", "exec_time_ms", "exec_type", "exec_fee",
                "is_foreign", "is_backfilled", "raw")


class DB:
    """Единый интерфейс к Postgres или SQLite (потокобезопасен, lock на запись). Движок per-instance
    по database_url (дефолт config.ops.DATABASE_URL: postgres:// → PG, иначе SQLite в db_path/
    config.ops.DB_PATH). owner=True создаёт схему. psycopg2 импортируется лениво (нужен только для PG)."""

    def __init__(self, *, database_url=None, db_path=None, owner=False):
        url = config.ops.DATABASE_URL if database_url is None else database_url
        self.is_pg = url.startswith("postgres://") or url.startswith("postgresql://")
        self._lock = threading.Lock()
        self._lock_conn = None      # отдельное соединение под advisory-lock (PG)
        self._lock_file = None      # файловый лок (SQLite)
        if self.is_pg:
            import psycopg2
            import psycopg2.extras  # noqa: F401  (RealDictCursor через self._pg.extras)
            from psycopg2.pool import ThreadedConnectionPool
            self._pg = psycopg2
            self._url = url
            self._integrity_err = psycopg2.IntegrityError   # PK-коллизия id (конкурентный писатель) -> retry
            self.pool = ThreadedConnectionPool(1, 6, dsn=url)
        else:
            import sqlite3
            self._path = config.ops.DB_PATH if db_path is None else db_path
            self._integrity_err = sqlite3.IntegrityError
            self.conn = sqlite3.connect(self._path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        if owner:
            self.ensure_schema()

    # ── низкоуровневые ──
    def _ph(self, sql):
        """%s -> ? для SQLite."""
        return sql if self.is_pg else sql.replace("%s", "?")

    def execute(self, sql, params=()):
        sql = self._ph(sql)
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                    conn.commit()
                except Exception:
                    conn.rollback()          # иначе aborted-транзакция вернётся в пул (min=1) → отложенный InFailedSqlTransaction у следующего вызова
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                self.conn.execute(sql, params)
                self.conn.commit()

    def query(self, sql, params=()):
        sql = self._ph(sql)
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    with conn.cursor(cursor_factory=self._pg.extras.RealDictCursor) as cur:
                        cur.execute(sql, params)
                        return [dict(r) for r in cur.fetchall()]
                except Exception:
                    conn.rollback()          # failed SELECT тоже abort'ит транзакцию PG → rollback перед возвратом в пул (иначе грязный conn)
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                cur = self.conn.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]

    def ensure_schema(self):
        self._migrate_scout_findings_tf_pk()      # ДО SCHEMA: дропнуть старый одноколоночный PK → composite ниже пересоздаст
        for stmt in SCHEMA:
            self.execute(stmt)
        self._migrate_capital_cursor_cols()
        self._migrate_log_cols()

    def _migrate_capital_cursor_cols(self):
        """Идемпотентно долить курсор-колонки в СУЩЕСТВУЮЩУЮ capital_state: CREATE TABLE IF NOT EXISTS НЕ
        добавляет колонки в уже созданную таблицу (Railway/PG после Вех 1–4). PG: ADD COLUMN IF NOT EXISTS.
        SQLite: PRAGMA-проверка (нет IF NOT EXISTS для колонок) + ADD COLUMN. compound-курсор — под-шаг 5a;
        close_all_ack_id (курсор исполненного «Закрыть всё») — под-шаг 5.3b."""
        cols = (("last_closed_ms", "BIGINT"), ("last_closed_ids", "TEXT"), ("close_all_ack_id", "BIGINT"),
                ("stop_streak", "INTEGER"),   # 5.7 п.4: дебаунс ложного STOP (2 тика подряд)
                ("idle_gap_ms", "BIGINT"),    # 5.7 п.5: латч тревоги «долгий простой >7д»
                ("last_4h_seen_ms", "BIGINT"), # 5.7 п.6: метка-якорь backfill таймаута-72
                ("warm_ack_id", "BIGINT"))    # 5.8 п.4a: курсор исполненного «Прогреть выбранные» (WARM_APPLY)
        if self.is_pg:
            for name, typ in cols:
                self.execute(f"ALTER TABLE capital_state ADD COLUMN IF NOT EXISTS {name} {typ}")
        else:
            existing = {r["name"] for r in self.query("PRAGMA table_info(capital_state)")}
            for name, typ in cols:
                if name not in existing:
                    self.execute(f"ALTER TABLE capital_state ADD COLUMN {name} {typ}")

    def _migrate_log_cols(self):
        """Идемпотентно долить лог-колонки в СУЩЕСТВУЮЩИЕ fills/events (CREATE TABLE IF NOT EXISTS не добавляет
        колонки в уже созданную таблицу — Railway/PG после Вех 1–5). Аддитивно, старые строки NULL → parity
        движка НЕ затрагивается (лог ОПРОСНОГО пути для офлайн-сверки с WS, Стадия B). ws_stage_b_preconditions:
        + структурный ключ выхода events(exit_link/order_id/lv/role/qty). PER-COLUMN try (аудит): битый ALTER →
        колонка ОСТАЁТСЯ NULL (офлайн-скрипт NULL-толерантен), НЕ роняет boot обоих сервисов."""
        add = {"fills": (("detect_bar_ms", "BIGINT"), ("order_id", "TEXT")),
               "events": (("ts_ms", "BIGINT"), ("exit_link", "TEXT"), ("order_id", "TEXT"),
                          ("lv", "REAL"), ("role", "TEXT"), ("qty", "REAL")),
               "heartbeat": (("drops", "BIGINT"), ("reconnect_count", "BIGINT"), ("msgs_received", "BIGINT"),
                             ("process_start_ms", "BIGINT"), ("last_exchange_ok_ms", "BIGINT"))}
        for table, cols in add.items():
            existing = (set() if self.is_pg
                        else {r["name"] for r in self.query(f"PRAGMA table_info({table})")})
            clause = "ADD COLUMN IF NOT EXISTS" if self.is_pg else "ADD COLUMN"
            for name, typ in cols:
                if not self.is_pg and name in existing:
                    continue
                try:
                    self.execute(f"ALTER TABLE {table} {clause} {name} {typ}")
                except Exception as e:                       # мягкая деградация: колонка NULL, не boot-краш обоих сервисов
                    get_logger("pifagor.db").warning("миграция %s.%s пропущена (останется NULL): %s", table, name, e)

    def _migrate_scout_findings_tf_pk(self):
        """scout_findings PK: symbol → (symbol, tf) (под-шаг 7, dual-ТФ 4h+1h). Таблица — РЕГЕНЕРИРУЕМЫЙ снимок
        последнего скана (история в scout_findings_log) → drop+recreate безопасен (пересоберётся первым сканом).
        Зовётся ДО SCHEMA: composite CREATE IF NOT EXISTS ниже пересоздаст. Идемпотентно: дропаем ТОЛЬКО старый
        одноколоночный PK (symbol); композитный/отсутствующий — no-op. Трогает ТОЛЬКО scout-таблицу — боевые
        таблицы воркёра не затрагиваются. Мягко: не роняем boot 3 сервисов из-за scout-снимка."""
        try:
            if self.is_pg:
                reg = self.query("SELECT to_regclass('scout_findings') AS r", ())
                if not reg or reg[0].get("r") is None:
                    return                                # таблицы ещё нет → SCHEMA создаст composite
                rows = self.query(
                    "SELECT kcu.column_name AS name FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name "
                    "WHERE tc.table_name='scout_findings' AND tc.constraint_type='PRIMARY KEY'", ())
                pk_cols = {r["name"] for r in rows}
            else:
                info = self.query("PRAGMA table_info(scout_findings)")
                if not info:
                    return                                # таблицы ещё нет (fresh SQLite)
                pk_cols = {r["name"] for r in info if r.get("pk")}
            if pk_cols and "tf" not in pk_cols:           # старый одноколоночный PK (symbol) → пересоздать composite
                self.execute("DROP TABLE IF EXISTS scout_findings")
                get_logger("pifagor.db").info("scout_findings мигрирована на PK (symbol,tf) — снимок пересоберётся")
        except Exception as e:                            # мягкая деградация: не роняем boot из-за scout-снимка
            get_logger("pifagor.db").warning("миграция scout_findings PK пропущена: %s", e)

    # ── single-instance lock (мульти-контейнер) ──
    def acquire_singleton(self, key=918273):
        """Эксклюзивный лок «я единственный воркер». True=взял, False=другой жив. PG:
        pg_try_advisory_lock на отдельном соединении (держится всю жизнь процесса) — защищает
        мульти-контейнерный деплой Railway (файловый лок там бесполезен: эфемерный диск per-container).
        SQLite: файловый лок. **При False закрываем хэндл соединения/файла** (иначе утечка conn/fd —
        аудит границы Вехи 3). Проводка в старт воркера — Веха 5 ф.5.5a (app/main.py)."""
        if self.is_pg:
            self._lock_conn = self._pg.connect(dsn=self._url)
            self._lock_conn.autocommit = True
            with self._lock_conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
                got = bool(cur.fetchone()[0])
            if not got:                       # лок занят другим воркером → не держим лишнее соединение
                self._lock_conn.close()
                self._lock_conn = None
            return got
        self._lock_file = open(self._path + ".lock", "w")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            self._lock_file.close()           # занят → закрыть хэндл (иначе утечка fd)
            self._lock_file = None
            return False

    def close(self):
        """Освободить ресурсы (идемпотентно): advisory-lock-соединение/файловый лок (закрытие сессии
        снимает pg advisory-lock) + основное соединение/пул. Воркер — в finally main(); дашборд —
        shutdown-хук (backlog); тесты — детерминированно (без зависимости от GC-тайминга/ResourceWarning)."""
        if self._lock_conn is not None:
            try:
                self._lock_conn.close()
            except Exception:
                pass
            self._lock_conn = None
        if self._lock_file is not None:
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None
        try:
            if self.is_pg:
                self.pool.closeall()
            else:
                self.conn.close()
        except Exception:
            pass

    # ── снимок сетапов (переживает рестарт; ADR 0008) ──
    def state_get(self, symbol):
        rows = self.query("SELECT payload FROM setup_state WHERE symbol=%s", (symbol,))
        return json.loads(rows[0]["payload"]) if rows else None

    def state_put(self, symbol, payload):
        """payload — dict карточки; сериализуем JSON-ом. (Card-aware сериализация — StateStore, под-шаг 3.)"""
        self.execute(
            "INSERT INTO setup_state(symbol,payload,updated_ts) VALUES(%s,%s,%s) "
            "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload, updated_ts=excluded.updated_ts",
            (symbol, json.dumps(payload, ensure_ascii=False), _utcnow_iso()))

    def state_clear(self, symbol):
        self.execute("DELETE FROM setup_state WHERE symbol=%s", (symbol,))

    def state_all(self):
        rows = self.query("SELECT symbol, payload FROM setup_state", ())
        return {r["symbol"]: json.loads(r["payload"]) for r in rows}

    def state_mutate(self, symbol, mutator):
        """АТОМАРНО (под локом; FOR UPDATE на PG): прочитать карточку, применить mutator(setup)->bool,
        при True записать обратно. Закрывает lost-update (WS-залив vs тик): read-modify-write в ОДНОМ
        критическом участке. Внутри лока — ТОЛЬКО сырое соединение (self.execute/query тоже берут
        self._lock -> дедлок). Возвращает результат mutator (False, если карточки нет).
        ВАЖНО: в mutator карточка со СТРОКОВЫМИ ключами ног (float-рекаст — только StateStore.get/all);
        обходи legs через .values(), НЕ индексируй legs[0.5] (будет KeyError)."""
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT payload FROM setup_state WHERE symbol=%s FOR UPDATE", (symbol,))
                        row = cur.fetchone()
                        if not row:
                            conn.rollback(); return False
                        setup = json.loads(row[0])
                        changed = mutator(setup)
                        if changed:
                            cur.execute("UPDATE setup_state SET payload=%s, updated_ts=%s WHERE symbol=%s",
                                        (json.dumps(setup, ensure_ascii=False), _utcnow_iso(), symbol))
                        conn.commit()
                        return changed
                except Exception:
                    conn.rollback()      # mutator упал -> снять FOR UPDATE-лок до возврата conn в пул
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                cur = self.conn.execute("SELECT payload FROM setup_state WHERE symbol=?", (symbol,))
                row = cur.fetchone()
                if not row:
                    return False
                setup = json.loads(row[0])
                changed = mutator(setup)
                if changed:
                    self.conn.execute("UPDATE setup_state SET payload=?, updated_ts=? WHERE symbol=?",
                                      (json.dumps(setup, ensure_ascii=False), _utcnow_iso(), symbol))
                    self.conn.commit()
                return changed

    # ── леджер капитала (единственная строка id=1; ADR 0010) ──
    def capital_get(self):
        """Строка леджера как dict (колонки CAPITAL_COLS + id/updated_ts) или None, если не засеян."""
        rows = self.query("SELECT * FROM capital_state WHERE id=1", ())
        return rows[0] if rows else None

    def capital_put(self, row):
        """Upsert единственной строки леджера (id=1). row — dict с колонками CAPITAL_COLS
        (отсутствующие -> NULL). Это ТОЛЬКО хранилище: ratio/инварианты считает risk_capital.ledger."""
        vals = [row.get(c) for c in CAPITAL_COLS]
        cols_sql = ",".join(CAPITAL_COLS)
        placeholders = ",".join(["%s"] * len(CAPITAL_COLS))
        set_sql = ",".join(f"{c}=excluded.{c}" for c in CAPITAL_COLS)
        self.execute(
            f"INSERT INTO capital_state(id,{cols_sql},updated_ts) VALUES(1,{placeholders},%s) "
            f"ON CONFLICT(id) DO UPDATE SET {set_sql}, updated_ts=excluded.updated_ts",
            (*vals, _utcnow_iso()))

    def capital_mutate(self, mutator):
        """АТОМАРНО (под локом; FOR UPDATE на PG): прочитать строку леджера (id=1), mutator(row)->bool,
        при True записать колонки CAPITAL_COLS обратно. Закрывает lost-update (рефинанс vs apply_pnl).
        Возвращает результат mutator (False, если строки нет — леджер не засеян)."""
        set_sql = ",".join(f"{c}=%s" for c in CAPITAL_COLS)
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    with conn.cursor(cursor_factory=self._pg.extras.RealDictCursor) as cur:
                        cur.execute("SELECT * FROM capital_state WHERE id=1 FOR UPDATE", ())
                        row = cur.fetchone()
                        if not row:
                            conn.rollback(); return False
                        row = dict(row)
                        changed = mutator(row)
                        if changed:
                            cur.execute(
                                f"UPDATE capital_state SET {set_sql}, updated_ts=%s WHERE id=1",
                                (*[row.get(c) for c in CAPITAL_COLS], _utcnow_iso()))
                        conn.commit()
                        return changed
                except Exception:
                    conn.rollback()      # mutator упал -> снять FOR UPDATE-лок до возврата conn в пул
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                cur = self.conn.execute("SELECT * FROM capital_state WHERE id=1")
                row = cur.fetchone()
                if not row:
                    return False
                row = dict(row)
                changed = mutator(row)
                if changed:
                    self.conn.execute(
                        self._ph(f"UPDATE capital_state SET {set_sql}, updated_ts=%s WHERE id=1"),
                        (*[row.get(c) for c in CAPITAL_COLS], _utcnow_iso()))
                    self.conn.commit()
                return changed

    # ── рантайм-крутилки (config_state key-value) + журнал (config_log); Веха 4 ф.2, docs/14 §3–4 ──
    def config_get(self, key):
        """Сырое TEXT-значение крутилки из config_state (парс — ConfigStore), либо None если не задано."""
        rows = self.query("SELECT value FROM config_state WHERE key=%s", (key,))
        return rows[0]["value"] if rows else None

    def config_all(self):
        """{key: value(TEXT)} всех заданных крутилок (типизация — ConfigStore)."""
        rows = self.query("SELECT key, value FROM config_state", ())
        return {r["key"]: r["value"] for r in rows}

    def config_apply(self, key, value, *, source, applied_from_bar=None):
        """АТОМАРНО (под локом): прочитать old из config_state; при old==new — no-op (False, без шума в
        журнале); иначе upsert config_state + append config_log (id=MAX+1, dual-engine без SERIAL).
        value/old хранятся как TEXT (str(); None остаётся NULL). applied_from_bar — INT|None (аудит,
        фича 4 передаёт «следующий 4h-бар»). Возвращает True, если изменение записано.
        Дашборд и воркер — ДВА писателя в config_log: их MAX+1 может совпасть (PK-коллизия id) -> retry-once."""
        new = None if value is None else str(value)
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    for attempt in range(2):
                        try:
                            with conn.cursor() as cur:
                                cur.execute("SELECT value FROM config_state WHERE key=%s", (key,))
                                r = cur.fetchone()
                                old = r[0] if r else None
                                if old == new:
                                    conn.rollback(); return False
                                cur.execute(
                                    "INSERT INTO config_state(key,value,updated_ts) VALUES(%s,%s,%s) "
                                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                                    (key, new, _utcnow_iso()))
                                cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM config_log")
                                next_id = cur.fetchone()[0]
                                cur.execute(
                                    "INSERT INTO config_log(id,ts,param,old,new,source,applied_from_bar) "
                                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                    (next_id, _utcnow_iso(), key, old, new, source, applied_from_bar))
                            conn.commit()
                            return True
                        except self._integrity_err:
                            conn.rollback()        # конкурент занял id -> пересчитать MAX+1 и повторить раз
                            if attempt:
                                raise
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                for attempt in range(2):
                    try:                   # инвариант: изменение config_state ⇒ запись в config_log (атомарно)
                        cur = self.conn.execute("SELECT value FROM config_state WHERE key=?", (key,))
                        r = cur.fetchone()
                        old = r[0] if r else None
                        if old == new:
                            return False
                        self.conn.execute(
                            "INSERT INTO config_state(key,value,updated_ts) VALUES(?,?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                            (key, new, _utcnow_iso()))
                        next_id = self.conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM config_log").fetchone()[0]
                        self.conn.execute(
                            "INSERT INTO config_log(id,ts,param,old,new,source,applied_from_bar) VALUES(?,?,?,?,?,?,?)",
                            (next_id, _utcnow_iso(), key, old, new, source, applied_from_bar))
                        self.conn.commit()
                        return True
                    except self._integrity_err:
                        self.conn.rollback()   # конкурент занял id -> повторить раз
                        if attempt:
                            raise
                    except Exception:
                        self.conn.rollback()   # откат частичной записи (state без log)
                        raise

    def config_log_append(self, param, old, new, *, source, applied_from_bar=None):
        """Append-only строка в config_log БЕЗ записи в config_state (audit-only: ДЕЙСТВИЯ дашборда —
        напр. «Закрыть всё», обычно source='action'). config_all()/overrides() её не видят (читают только
        config_state). id=MAX+1 под локом + retry-once при конкурентном писателе (дашборд+воркер на PG могут
        выбрать одинаковый id -> PK-коллизия). old/new -> TEXT|None. Возвращает id записанной строки."""
        o = None if old is None else str(old)
        n = None if new is None else str(new)
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    for attempt in range(2):
                        try:
                            with conn.cursor() as cur:
                                cur.execute("SELECT COALESCE(MAX(id),0)+1 FROM config_log")
                                next_id = cur.fetchone()[0]
                                cur.execute(
                                    "INSERT INTO config_log(id,ts,param,old,new,source,applied_from_bar) "
                                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                    (next_id, _utcnow_iso(), param, o, n, source, applied_from_bar))
                            conn.commit()
                            return next_id
                        except self._integrity_err:
                            conn.rollback()
                            if attempt:
                                raise
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                for attempt in range(2):
                    try:
                        next_id = self.conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM config_log").fetchone()[0]
                        self.conn.execute(
                            "INSERT INTO config_log(id,ts,param,old,new,source,applied_from_bar) VALUES(?,?,?,?,?,?,?)",
                            (next_id, _utcnow_iso(), param, o, n, source, applied_from_bar))
                        self.conn.commit()
                        return next_id
                    except self._integrity_err:
                        self.conn.rollback()
                        if attempt:
                            raise

    def config_log_all(self, param=None, limit=None):
        """Журнал изменений (новые сверху, id DESC). param — фильтр по крутилке; limit — N последних.
        Возвращает list[dict] с колонками id/ts/param/old/new/source/applied_from_bar."""
        sql = "SELECT id, ts, param, old, new, source, applied_from_bar FROM config_log"
        params = []
        if param is not None:
            sql += " WHERE param=%s"; params.append(param)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        return self.query(sql, tuple(params))

    def config_log_latest(self, param):
        """Самая свежая строка config_log по param (по id DESC) или None. = config_log_all(param, limit=1)[0].
        Намерение «Закрыть всё» = последняя CLOSE_ALL-строка; воркер-энфорсмент (5.3c) сверит её id с ack-курсором."""
        rows = self.config_log_all(param=param, limit=1)
        return rows[0] if rows else None

    # ── писатели логовых таблиц (Веха 5): пишет воркер ──
    def heartbeat_put(self, *, ts_ms, active_setups, ws_alive=False, last_ws_ms=None, note="",
                      drops=None, reconnect_count=None, msgs_received=None,
                      process_start_ms=None, last_exchange_ok_ms=None):
        """Пульс бота (одна строка id=1, upsert): «жив» + ts_ms/active_setups/ws_alive для монитора.
        ws_alive хранится TEXT 'yes'/'no' (так читает дашборд). drops/reconnect_count/msgs_received
        (ws_stage_b_preconditions): ТЕКУЩИЙ снимок счётчиков тени (NULL при OFF). process_start_ms/
        last_exchange_ok_ms (bot_health): метка старта процесса + время последнего успешного вызова Bybit
        (NULL до первого успеха). Зовётся каждый тик."""
        self.execute(
            "INSERT INTO heartbeat(id,ts,ts_ms,active_setups,ws_alive,last_ws_ms,note,drops,reconnect_count,"
            "msgs_received,process_start_ms,last_exchange_ok_ms) "
            "VALUES(1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, active_setups=excluded.active_setups, "
            "ws_alive=excluded.ws_alive, last_ws_ms=excluded.last_ws_ms, note=excluded.note, "
            "drops=excluded.drops, reconnect_count=excluded.reconnect_count, msgs_received=excluded.msgs_received, "
            "process_start_ms=excluded.process_start_ms, last_exchange_ok_ms=excluded.last_exchange_ok_ms",
            (_utcnow_iso(), int(ts_ms), int(active_setups), "yes" if ws_alive else "no", last_ws_ms, note,
             drops, reconnect_count, msgs_received, process_start_ms, last_exchange_ok_ms))

    def worker_config_put(self, defaults, *, now_ms):
        """Снимок env-ДЕФОЛТОВ воркера (фича unified_config_source): одна строка id=1, upsert. defaults —
        dict {knob: значение} → JSON. Пишет ТОЛЬКО воркер НА СТАРТЕ (env статичен на процесс). Дашборд читает
        для показа: override(config_state, общий) ← этот дефолт ← свой env — чтобы показ не врал про env-крутилки."""
        self.execute(
            "INSERT INTO worker_config(id,ts,defaults,updated_ms) VALUES(1,%s,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, defaults=excluded.defaults, updated_ms=excluded.updated_ms",
            (_utcnow_iso(), json.dumps(defaults, ensure_ascii=False), int(now_ms)))

    def _append_row(self, table, row):
        """Append-only вставка одной строки в логовую таблицу (signals/fills/events/equity_history): id=MAX(id)+1
        под локом + retry-once при PK-коллизии (дашборд+воркер на PG могут выбрать одинаковый id). row — dict
        колонка→значение БЕЗ id. Зеркало скелета `config_log_append`; НЕ через `self.execute` (повторный
        `self._lock` → дедлок). Возвращает id записанной строки."""
        cols = list(row.keys())
        col_sql = ",".join(cols)
        placeholders = ",".join(["%s"] * (len(cols) + 1))       # +1 под id
        vals = [row[c] for c in cols]
        ins = f"INSERT INTO {table}(id,{col_sql}) VALUES({placeholders})"
        maxsql = f"SELECT COALESCE(MAX(id),0)+1 FROM {table}"
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    for attempt in range(2):
                        try:
                            with conn.cursor() as cur:
                                cur.execute(maxsql)
                                next_id = cur.fetchone()[0]
                                cur.execute(ins, (next_id, *vals))
                            conn.commit()
                            return next_id
                        except self._integrity_err:
                            conn.rollback()
                            if attempt:
                                raise
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                ins_q = self._ph(ins)
                for attempt in range(2):
                    try:
                        next_id = self.conn.execute(maxsql).fetchone()[0]
                        self.conn.execute(ins_q, (next_id, *vals))
                        self.conn.commit()
                        return next_id
                    except self._integrity_err:
                        self.conn.rollback()
                        if attempt:
                            raise

    def account_put(self, *, total_equity=None, usdt_equity=None, realised_pnl=None,
                    closed_trades=None, positions=None):
        """Снимок счёта (одна строка id=1, upsert): equity/usdt/realised_pnl/closed_trades + positions JSON.
        КЕЙСТОУН монитора (Веха 5 ф.5.4b): любая строка → viewmodel `equity_live=True`, активирует просадку/
        below_kill. ЗВАТЬ ТОЛЬКО при валидной `total_equity` (fail-open в 5.4b) — NULL включил бы фантом-STOP.
        positions — list[dict]|None → json.dumps (TEXT; читатель `_parse_json`)."""
        pos = json.dumps(positions if isinstance(positions, list) else [], ensure_ascii=False)
        self.execute(
            "INSERT INTO account(id,ts,total_equity,usdt_equity,realised_pnl,closed_trades,positions) "
            "VALUES(1,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, "
            "total_equity=excluded.total_equity, usdt_equity=excluded.usdt_equity, "
            "realised_pnl=excluded.realised_pnl, closed_trades=excluded.closed_trades, positions=excluded.positions",
            (_utcnow_iso(), total_equity, usdt_equity, realised_pnl, closed_trades, pos))

    def orders_open_put(self, symbol, payload):
        """Снимок ждущих ордеров символа (per-symbol upsert): payload (dict) → JSON. Веха 5 ф.5.4d. При уходе
        символа из активного состояния снимать строку `orders_open_clear` (иначе фантомные «ждущие» на мониторе)."""
        self.execute(
            "INSERT INTO orders_open(symbol,ts,payload) VALUES(%s,%s,%s) "
            "ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts, payload=excluded.payload",
            (symbol, _utcnow_iso(), json.dumps(payload, ensure_ascii=False)))

    def orders_open_clear(self, symbol):
        """Удалить снимок ждущих ордеров символа (сетап закрыт/реконсилирован) — панель не показывает фантом."""
        self.execute("DELETE FROM orders_open WHERE symbol=%s", (symbol,))

    def signals_put(self, *, symbol, side, ts=None, bar_time=None, min_bar_pct=None, a=None, b=None,
                    entry_0382=None, entry_05=None, entry_0618=None, stop=None,
                    tgt_0382=None, tgt_05=None, tgt_0618=None,
                    shadow_would_touch=None, shadow_same_bar=None, shadow_outcome=None, shadow_ret_pct=None):
        """Строка ленты сигналов (append, Веха 5 ф.5.4c) — на рождении сигнала. shadow_* — нет live-продьюсера
        теневого касания → NULL (тайл fill-rate off до 5.6). Возвращает id."""
        return self._append_row("signals", {
            "ts": ts or _utcnow_iso(), "symbol": symbol, "side": side, "bar_time": bar_time,
            "min_bar_pct": min_bar_pct, "a": a, "b": b,
            "entry_0382": entry_0382, "entry_05": entry_05, "entry_0618": entry_0618, "stop": stop,
            "tgt_0382": tgt_0382, "tgt_05": tgt_05, "tgt_0618": tgt_0618,
            "shadow_would_touch": shadow_would_touch, "shadow_same_bar": shadow_same_bar,
            "shadow_outcome": shadow_outcome, "shadow_ret_pct": shadow_ret_pct})

    def fills_put(self, *, symbol, side, entry_level, ts=None, order_link_id=None, requested_price=None,
                  exec_price=None, slip_pct=None, requested_qty=None, exec_qty=None, partial=None,
                  exec_fee=None, fee_rate=None, exec_type=None, balance_used=None, risk_pct=None,
                  stop_distance_pct=None, nominal_usd=None, leverage_eff=None, same_bar_flag=None,
                  filled_pre_rebuild=None, detect_bar_ms=None, order_id=None):
        """Строка истории заливов (append, Веха 5 ф.5.4c) — на переходе ноги (mark_filled). cost/risk-колонки
        NULL на опросном пути (нет execution-record). ENTRY-vs-EXIT фильтр — на стороне хука. detect_bar_ms/
        order_id (5.2 п6): граница 15m обнаружения залива опросом + orderId для офлайн-сверки края с WS. Возвращает id."""
        return self._append_row("fills", {
            "ts": ts or _utcnow_iso(), "symbol": symbol, "side": side, "entry_level": entry_level,
            "order_link_id": order_link_id, "requested_price": requested_price, "exec_price": exec_price,
            "slip_pct": slip_pct, "requested_qty": requested_qty, "exec_qty": exec_qty, "partial": partial,
            "exec_fee": exec_fee, "fee_rate": fee_rate, "exec_type": exec_type, "balance_used": balance_used,
            "risk_pct": risk_pct, "stop_distance_pct": stop_distance_pct, "nominal_usd": nominal_usd,
            "leverage_eff": leverage_eff, "same_bar_flag": same_bar_flag, "filled_pre_rebuild": filled_pre_rebuild,
            "detect_bar_ms": detect_bar_ms, "order_id": order_id})

    def events_put(self, *, symbol, event, detail=None, ts=None, ts_ms=None,
                   exit_link=None, order_id=None, lv=None, role=None, qty=None):
        """Строка журнала событий (append, Веха 5 ф.5.4c) — lifecycle/защита (placed/close/timeout/CLOSE_ALL/
        kill-switch STOP/refinance). detail → TEXT|None. ts_ms (5.2 п6): для leg_exit — граница 15m обнаружения
        выхода опросом. exit_link/order_id/lv/role/qty (ws_stage_b_preconditions): СТРУКТУРНЫЙ ключ выхода для
        офлайн-сверки края Стадии B (leg_exit; прочие события — NULL). Возвращает id."""
        return self._append_row("events", {
            "ts": ts or _utcnow_iso(), "symbol": symbol, "event": event,
            "detail": None if detail is None else str(detail), "ts_ms": ts_ms,
            "exit_link": exit_link, "order_id": order_id, "lv": lv, "role": role, "qty": qty})

    def equity_history_put(self, *, ts_ms, total_equity=None, realised_pnl=None, closed_trades=None, ts=None):
        """Точка кривой капитала (append, Веха 5 ф.5.4b) — по явной каденции (~1ч, не каждый тик). ts_ms BIGINT
        (ось X графика). Возвращает id."""
        return self._append_row("equity_history", {
            "ts": ts or _utcnow_iso(), "ts_ms": int(ts_ms), "total_equity": total_equity,
            "realised_pnl": realised_pnl, "closed_trades": closed_trades})

    def closed_trade_put(self, *, created_ms, symbol=None, side=None, qty=None,
                         avg_entry=None, avg_exit=None, closed_pnl=None, order_id=None, ts=None):
        """Строка журнала ЗАКРЫТЫХ сделок (trade_history_pnl) — воркер до-сохраняет РЕАЛЬНУЮ Bybit closed-pnl
        строку (уже тянет для компаунда). ИДЕМПОТЕНТНО по dedup_key = ПОЛНОЙ идентичности строки
        (created_ms|order_id|closed_pnl|qty|symbol|side|avg_entry|avg_exit) — ON CONFLICT DO NOTHING: ре-полл
        после краха ДО персиста delta-курсора даёт байт-идентичные строки → тот же ключ → НЕ задваивает. Ключ НЕ
        (created_ms, order_id): компаунд суммирует closed-pnl как МУЛЬТИМНОЖЕСТВО (orderId не уникален на строку,
        bybit_client.py:186 — несколько строк одного ордера складываются в working), поэтому журнал хранит те же
        строки, иначе сумма P&L разойдётся с working; NULL order_id безопасен (в ключе → "None"). Предел: две
        БАЙТ-идентичные строки (неотличимы от ре-полла) схлопнутся в одну — реальные разные закрытия отличаются в
        closed_pnl/qty. id=MAX(id)+1 под локом + retry-once при PK-коллизии id (НЕ через self.execute — повторный
        self._lock → дедлок). Возвращает число вставленных (0 — дубль/уже есть, 1 — новая)."""
        cms = int(created_ms)
        # СТАБИЛЬНЫЙ дедуп (created_ms, order_id, closed_pnl-до-цента) — устойчив к ВОЛАТИЛЬНЫМ display-полям Bybit:
        # avg_entry/avg_exit/qty могут прийти None→значение между пере-чтениями journal_sync ⇒ полный dedup_key дал бы
        # ДУБЛЬ, а closed_trades_pnl_total (плашка «Реализовано») его бы задвоил. ⚠ closed_pnl сравниваем ЧЕРЕЗ
        # ROUND(...,2), А НЕ точно: на Postgres колонка REAL=float4 (4 байта) хранит 57.6 как 57.599998 → точное
        # `=57.6` (float8-параметр) дало бы FALSE → дубль (на SQLite REAL=double, потому юнит-тесты этого НЕ ловили).
        # Округление до цента storage-независимо (float4/float8 → один результат) и чинит уже записанные float4-строки
        # без миграции. Мультимножество цело: разный P&L-до-цента = разная строка (тест test_dashboard_db:158-159).
        # Воркёр — ЕДИНСТВЕННЫЙ писатель (однопоток) ⇒ SELECT ВНЕ лока без TOCTOU (self.query берёт свой лок).
        # dedup_key(полная идентичность)+ON CONFLICT ниже остаётся backstop (в т.ч. для None closed_pnl, где ROUND=NULL).
        # NULL-safe order_id: IS NOT DISTINCT FROM (pg) / IS (sqlite).
        _nsf = "IS NOT DISTINCT FROM" if self.is_pg else "IS"
        _pnl = ("ROUND(closed_pnl::numeric,2)=ROUND(%s::numeric,2)" if self.is_pg
                else "ROUND(closed_pnl,2)=ROUND(%s,2)")
        if self.query(f"SELECT 1 FROM closed_trades WHERE created_ms=%s AND order_id {_nsf} %s "
                      f"AND {_pnl} LIMIT 1", (cms, order_id, closed_pnl)):
            return 0
        dedup_key = "|".join(str(x) for x in (cms, order_id, closed_pnl, qty, symbol, side, avg_entry, avg_exit))
        cols = ("ts", "created_ms", "symbol", "side", "qty", "avg_entry", "avg_exit", "closed_pnl", "order_id", "dedup_key")
        vals = (ts or _utcnow_iso(), cms, symbol, side, qty, avg_entry, avg_exit, closed_pnl, order_id, dedup_key)
        col_sql = ",".join(cols)
        placeholders = ",".join(["%s"] * (len(cols) + 1))       # +1 под id
        ins = (f"INSERT INTO closed_trades(id,{col_sql}) VALUES({placeholders}) "
               f"ON CONFLICT(dedup_key) DO NOTHING")
        maxsql = "SELECT COALESCE(MAX(id),0)+1 FROM closed_trades"
        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    for attempt in range(2):
                        try:
                            with conn.cursor() as cur:
                                cur.execute(maxsql)
                                next_id = cur.fetchone()[0]
                                cur.execute(ins, (next_id, *vals))
                                n = cur.rowcount
                            conn.commit()
                            return n
                        except self._integrity_err:
                            conn.rollback()
                            if attempt:
                                raise
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                ins_q = self._ph(ins)
                for attempt in range(2):
                    try:
                        next_id = self.conn.execute(maxsql).fetchone()[0]
                        n = self.conn.execute(ins_q, (next_id, *vals)).rowcount
                        self.conn.commit()
                        return n
                    except self._integrity_err:
                        self.conn.rollback()
                        if attempt:
                            raise
                    except Exception:                           # симметрия с config_apply: не-integrity сбой → rollback, не грязный conn
                        self.conn.rollback()
                        raise

    # ── read-методы дашборда (Веха 4 ф.3): только ЧТЕНИЕ логовых таблиц ──
    def heartbeat_get(self):
        """Последний heartbeat (жив/ws_alive/active_setups/last_ws_ms + счётчики тени + метки bot_health) или None."""
        rows = self.query("SELECT id, ts, ts_ms, active_setups, ws_alive, last_ws_ms, note, "
                          "drops, reconnect_count, msgs_received, process_start_ms, last_exchange_ok_ms "
                          "FROM heartbeat ORDER BY id DESC LIMIT 1", ())
        return rows[0] if rows else None

    def boot_count_since(self, ms):
        """Число стартов воркера (событий worker_boot) за окно ts_ms >= ms → «перезапусков за 24ч» (bot_health).
        Считает boot'ы честно (деплой тоже = boot). 0, если событий/таблицы нет (fail-soft)."""
        try:
            rows = self.query("SELECT COUNT(*) AS n FROM events WHERE event='worker_boot' AND ts_ms >= %s",
                              (int(ms),))
            return int(rows[0]["n"]) if rows else 0
        except Exception:
            return 0

    def worker_config_get(self):
        """Снимок env-дефолтов воркера: {'defaults': {knob: value}, 'updated_ms': int} или None. FAIL-SOFT:
        воркер не писал / битый JSON / нет таблицы / любая ошибка → None (битый снимок НЕ роняет «Настройки»
        дашборда — он падает на свой env-дефолт = текущее поведение)."""
        try:
            rows = self.query("SELECT defaults, updated_ms FROM worker_config WHERE id=1", ())
            if not rows:
                return None
            row = rows[0]
            d = json.loads(row.get("defaults")) if row.get("defaults") else None
            if not isinstance(d, dict):
                return None
            return {"defaults": d, "updated_ms": row.get("updated_ms")}
        except Exception:
            return None

    def account_get(self):
        """Снимок счёта (одна строка id=1: equity/usdt/realised_pnl/closed_trades/positions JSON) или None."""
        rows = self.query("SELECT id, ts, total_equity, usdt_equity, realised_pnl, closed_trades, positions "
                          "FROM account WHERE id=1", ())
        return rows[0] if rows else None

    def equity_history_recent(self, limit=500, since_ms=None):
        """Точки кривой капитала, по возрастанию ts_ms (для графика). limit — кап последних N точек (None=без капа);
        since_ms — окно времени (ts_ms >= since_ms; индекс idx_eqhist_ts), None = вся история (пилюля «Всё»)."""
        sql = "SELECT id, ts, ts_ms, total_equity, realised_pnl, closed_trades FROM equity_history"
        params = []
        if since_ms is not None:
            sql += " WHERE ts_ms >= %s"; params.append(since_ms)
        sql += " ORDER BY ts_ms DESC"
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        rows = self.query(sql, tuple(params))
        return list(reversed(rows))                         # вернуть по возрастанию времени (для оси X)

    def equity_first_ts_ms(self):
        """Самая ранняя точка кривой (MIN ts_ms) — оценка размаха истории: какие пилюли периода реально доступны
        (напр. «30д» недоступна, пока бот наработал <30 дней). None, если истории ещё нет."""
        rows = self.query("SELECT MIN(ts_ms) AS t FROM equity_history", ())
        t = rows[0].get("t") if rows else None
        return int(t) if t is not None else None

    def signals_recent(self, limit=50):
        """Лента сигналов (новые сверху). Для fill-rate знаменателя shadow_would_touch — отдельной агрегацией."""
        sql = "SELECT * FROM signals ORDER BY id DESC"
        params = []
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        return self.query(sql, tuple(params))

    def fills_recent(self, limit=50):
        """История заливов/исполнений (новые сверху)."""
        sql = "SELECT * FROM fills ORDER BY id DESC"
        params = []
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        return self.query(sql, tuple(params))

    def events_recent(self, limit=50):
        """Журнал событий бота (новые сверху)."""
        sql = "SELECT id, ts, symbol, event, detail FROM events ORDER BY id DESC"
        params = []
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        return self.query(sql, tuple(params))

    def closed_trades_recent(self, limit=200):
        """Журнал ЗАКРЫТЫХ сделок с per-trade P&L (новые сверху по created_ms; tie-break id). Пусто до первых
        закрытий → [] (trade_history_pnl; пишет воркер из Bybit closed-pnl, читает «История» дашборда).
        limit=200 (было 50) — запас показа под накопление истории (полнота суммы — в closed_trades_pnl_total)."""
        sql = "SELECT * FROM closed_trades ORDER BY created_ms DESC, id DESC"
        params = []
        if limit is not None:
            sql += " LIMIT %s"; params.append(limit)
        return self.query(sql, tuple(params))

    def closed_trades_pnl_total(self):
        """Суммарный реализованный P&L по всему журналу закрытых сделок (для плашки «Баланс счёта» →
        «Реализовано»; account-writer realised_pnl НЕ пишет). Пусто → 0.0. Fail-soft: нет таблицы/ошибка → 0.0."""
        try:
            rows = self.query("SELECT COALESCE(SUM(closed_pnl),0) AS s FROM closed_trades", ())
            return float(rows[0]["s"]) if rows and rows[0].get("s") is not None else 0.0
        except Exception:
            return 0.0

    def orders_open_all(self):
        """Снимки открытых ордеров по символам (list[dict]: symbol, ts, payload JSON-строка)."""
        return self.query("SELECT symbol, ts, payload FROM orders_open ORDER BY symbol", ())

    def warm_candidates_put(self, symbol, payload):
        """Снимок warm-кандидата символа (per-symbol upsert): payload (дескриптор warm.classify) → JSON. Веха 5.8
        п.4a. Монета без кандидата → снять `warm_candidates_clear` (иначе стале-кандидат в превью дашборда)."""
        self.execute(
            "INSERT INTO warm_candidates(symbol,ts,payload) VALUES(%s,%s,%s) "
            "ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts, payload=excluded.payload",
            (symbol, _utcnow_iso(), json.dumps(payload, ensure_ascii=False)))

    def warm_candidates_clear(self, symbol):
        """Удалить снимок warm-кандидата символа (больше не кандидат / монета ведётся) — превью без фантома."""
        self.execute("DELETE FROM warm_candidates WHERE symbol=%s", (symbol,))

    def warm_candidates_all(self):
        """Снимки warm-кандидатов по символам (list[dict]: symbol, ts, payload JSON-строка) — для превью дашборда."""
        return self.query("SELECT symbol, ts, payload FROM warm_candidates ORDER BY symbol", ())

    def scan_snapshot_put(self, *, coins_scanned, signals_found, candidates, now_ms):
        """Снимок последнего 4h-скана (одна строка id=1, upsert): сколько монет проверено/сигналов родилось +
        список греющихся кандидатов (JSON). Пишет воркер на 4h-границе; дашборд читает (bot_health под-шаг 3)."""
        self.execute(
            "INSERT INTO scan_snapshot(id,ts,ts_ms,coins_scanned,signals_found,payload) VALUES(1,%s,%s,%s,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, "
            "coins_scanned=excluded.coins_scanned, signals_found=excluded.signals_found, payload=excluded.payload",
            (_utcnow_iso(), int(now_ms), int(coins_scanned), int(signals_found),
             json.dumps(candidates, ensure_ascii=False)))

    def scan_snapshot_get(self):
        """Снимок последнего 4h-скана: {ts_ms, coins_scanned, signals_found, candidates:[...]} или None.
        FAIL-SOFT: нет строки/битый JSON/нет таблицы → None (не роняет дашборд)."""
        try:
            rows = self.query("SELECT ts_ms, coins_scanned, signals_found, payload FROM scan_snapshot WHERE id=1", ())
            if not rows:
                return None
            r = rows[0]
            cands = json.loads(r.get("payload")) if r.get("payload") else []
            return {"ts_ms": r.get("ts_ms"), "coins_scanned": r.get("coins_scanned"),
                    "signals_found": r.get("signals_found"),
                    "candidates": cands if isinstance(cands, list) else []}
        except Exception:
            return None

    # ── Сканер-разведчик (Веха 7): скаут ПИШЕТ вселенную/мету, дашборд ЧИТАЕТ (страница «Разведчик») ──
    def scout_universe_put_many(self, rows, now_ms):
        """Апсерт per-symbol вселенной Этапа A (snapshot-семантика: символ PK). rows — list[dict] с ключами
        symbol/score/payload (payload = per-symbol dict метрик+отсевов). Единственный писатель — скаут."""
        ts = _utcnow_iso()
        for r in rows:
            self.execute(
                "INSERT INTO scout_universe(symbol,ts,ts_ms,score,payload) VALUES(%s,%s,%s,%s,%s) "
                "ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, "
                "score=excluded.score, payload=excluded.payload",
                (r["symbol"], ts, int(now_ms), float(r.get("score") or 0.0),
                 json.dumps(r.get("payload"), ensure_ascii=False)))

    def scout_universe_all(self):
        """Вся вселенная последнего Этапа A по убыванию скора (list[dict]: symbol, ts, ts_ms, score, payload)."""
        return self.query("SELECT symbol, ts, ts_ms, score, payload FROM scout_universe ORDER BY score DESC", ())

    def scout_meta_put(self, *, stage, funnel, now_ms, duration_s=None):
        """Снимок последнего прогона скаута (single-row id=1, upsert): стадия/воронка/тайминги (шапка страницы)."""
        payload = {"stage": stage, "funnel": funnel, "duration_s": duration_s}
        self.execute(
            "INSERT INTO scout_meta(id,ts,ts_ms,payload) VALUES(1,%s,%s,%s) "
            "ON CONFLICT(id) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, payload=excluded.payload",
            (_utcnow_iso(), int(now_ms), json.dumps(payload, ensure_ascii=False)))

    def scout_meta_get(self):
        """Снимок последнего прогона скаута ({ts, ts_ms, stage, funnel, duration_s}) или None. FAIL-SOFT."""
        try:
            rows = self.query("SELECT ts, ts_ms, payload FROM scout_meta WHERE id=1", ())
            if not rows:
                return None
            r = rows[0]
            p = json.loads(r.get("payload")) if r.get("payload") else {}
            return {"ts": r.get("ts"), "ts_ms": r.get("ts_ms"), **(p if isinstance(p, dict) else {})}
        except Exception:
            return None

    def scout_list_put_snapshot(self, rows, now_ms):
        """Курированный список (SNAPSHOT: удалить выпавшие символы + upsert текущие). rows — list[dict] с ключами
        symbol/score/mb1/mb2/bar_source (+ весь dict в payload). Единственный писатель — скаут (под-шаг 2)."""
        ts = _utcnow_iso()
        syms = [r["symbol"] for r in rows]
        if syms:
            ph = ",".join(["%s"] * len(syms))
            self.execute(f"DELETE FROM scout_list WHERE symbol NOT IN ({ph})", tuple(syms))
        else:
            self.execute("DELETE FROM scout_list", ())
        for r in rows:
            self.execute(
                "INSERT INTO scout_list(symbol,ts,ts_ms,score,mb1,mb2,bar_source,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts, "
                "ts_ms=excluded.ts_ms, score=excluded.score, mb1=excluded.mb1, mb2=excluded.mb2, "
                "bar_source=excluded.bar_source, payload=excluded.payload",
                (r["symbol"], ts, int(now_ms), float(r.get("score") or 0.0),
                 float(r["mb1"]), float(r["mb2"]), r.get("bar_source"),
                 json.dumps(r, ensure_ascii=False)))

    def scout_list_all(self):
        """Курированный список по убыванию скора (list[dict]: symbol, ts, ts_ms, score, mb1, mb2, bar_source, payload)."""
        return self.query(
            "SELECT symbol, ts, ts_ms, score, mb1, mb2, bar_source, payload FROM scout_list ORDER BY score DESC", ())

    # ── ROLLING кэш свечей (под-шаг 2b): скаут пишет, скан/график читают из БД ──
    def scout_klines_put_many(self, symbol, tf, candles):
        """Батч-upsert свечей (symbol,tf). candles — list dict {time,open,high,low,close,volume}. Идемпотентно
        по PK (symbol,tf,time_ms): повторный/перекрывающий докач НЕ дублит. Мульти-row VALUES чанками. Возвращает
        число обработанных строк. (Свечи одного fetch имеют уникальные time → нет intra-чанк дублей для PG.)"""
        rows = candles or []
        if not rows:
            return 0
        cols = "symbol,tf,time_ms,open,high,low,close,volume"
        total = 0
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            vals = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s)"] * len(chunk))
            params = []
            for c in chunk:
                params += [symbol, tf, int(c["time"]), float(c["open"]), float(c["high"]),
                           float(c["low"]), float(c["close"]), float(c.get("volume") or 0.0)]
            self.execute(
                f"INSERT INTO scout_klines({cols}) VALUES {vals} "
                "ON CONFLICT(symbol,tf,time_ms) DO UPDATE SET open=excluded.open, high=excluded.high, "
                "low=excluded.low, close=excluded.close, volume=excluded.volume", tuple(params))
            total += len(chunk)
        return total

    def scout_klines_last_ms(self, symbol, tf):
        """Время последнего кэшированного бара (symbol,tf) в мс или None (пустой кэш)."""
        r = self.query("SELECT MAX(time_ms) AS m FROM scout_klines WHERE symbol=%s AND tf=%s", (symbol, tf))
        return r[0]["m"] if r and r[0].get("m") is not None else None

    def scout_klines_read_window(self, symbol, tf, n):
        """Последние n свечей (symbol,tf) в ХРОНОЛОГИИ (по возрастанию). Формат = broker/bybit_client.get_klines."""
        rows = self.query(
            "SELECT time_ms,open,high,low,close,volume FROM scout_klines WHERE symbol=%s AND tf=%s "
            "ORDER BY time_ms DESC LIMIT %s", (symbol, tf, int(n)))
        out = [{"time": r["time_ms"], "open": r["open"], "high": r["high"], "low": r["low"],
                "close": r["close"], "volume": r["volume"]} for r in rows]
        out.reverse()
        return out

    def scout_klines_prune(self, symbol, tf, retention):
        """Оставить только newest `retention` свечей (symbol,tf); старше — удалить. Прунинг скользящего окна."""
        r = self.query(
            "SELECT time_ms FROM scout_klines WHERE symbol=%s AND tf=%s ORDER BY time_ms DESC LIMIT 1 OFFSET %s",
            (symbol, tf, int(retention)))
        if not r:
            return 0
        cutoff = r[0]["time_ms"]
        self.execute("DELETE FROM scout_klines WHERE symbol=%s AND tf=%s AND time_ms <= %s",
                     (symbol, tf, int(cutoff)))
        return 1

    # ── находки скана (под-шаг 3): снимок текущего скана + append-журнал ──
    def scout_findings_put_snapshot(self, rows, now_ms, tf=None):
        """Снимок находок Этапа B для ТФ `tf` (SNAPSHOT per-ТФ: удалить выпавшие символы ЭТОГО ТФ + upsert
        текущие). tf-скоуп (под-шаг 7) → скан 4h НЕ стирает находки 1h и наоборот. tf=None (легаси) → берём
        из первой строки. rows — list[dict] с symbol/status/tf/score (+ весь dict в payload). Писатель — скаут."""
        ts = _utcnow_iso()
        if tf is None:
            tf = rows[0].get("tf") if rows else None
        syms = [r["symbol"] for r in rows]
        if tf is None:                                     # без ТФ (не должно) — полный снапшот старой семантики
            if syms:
                ph = ",".join(["%s"] * len(syms))
                self.execute(f"DELETE FROM scout_findings WHERE symbol NOT IN ({ph})", tuple(syms))
            else:
                self.execute("DELETE FROM scout_findings", ())
        elif syms:
            ph = ",".join(["%s"] * len(syms))
            self.execute(f"DELETE FROM scout_findings WHERE tf=%s AND symbol NOT IN ({ph})", (tf, *syms))
        else:
            self.execute("DELETE FROM scout_findings WHERE tf=%s", (tf,))
        for r in rows:
            self.execute(
                "INSERT INTO scout_findings(symbol,ts,ts_ms,status,tf,score,payload) VALUES(%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(symbol,tf) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, status=excluded.status, "
                "score=excluded.score, payload=excluded.payload",
                (r["symbol"], ts, int(now_ms), r.get("status"), r.get("tf") or tf,
                 float(r.get("score") or 0.0), json.dumps(r, ensure_ascii=False)))

    def scout_findings_all(self):
        """Находки последнего скана по убыванию скора (list[dict]: symbol, ts, ts_ms, status, tf, score, payload)."""
        return self.query(
            "SELECT symbol, ts, ts_ms, status, tf, score, payload FROM scout_findings ORDER BY score DESC", ())

    def scout_finding_get(self, symbol, tf=None):
        """Текущая находка символа (распарсенный payload + status/tf/score) или None. tf=None → предпочесть 4h
        (дефолт показа), иначе первую (под-шаг 7: у символа теперь до 2 строк — 4h и 1h). FAIL-SOFT."""
        try:
            if tf is not None:
                rows = self.query("SELECT status, tf, score, payload FROM scout_findings WHERE symbol=%s AND tf=%s",
                                  (symbol, tf))
            else:
                rows = self.query(
                    "SELECT status, tf, score, payload FROM scout_findings WHERE symbol=%s "
                    "ORDER BY CASE WHEN tf=%s THEN 0 ELSE 1 END LIMIT 1", (symbol, "4h"))
            if not rows:
                return None
            r = rows[0]
            p = json.loads(r.get("payload")) if r.get("payload") else {}
            if not isinstance(p, dict):
                p = {}
            p["status"], p["tf"], p["score"] = r.get("status"), r.get("tf"), r.get("score")
            return p
        except Exception:
            return None

    # ── закладки владельца (под-шаг 6): снимок точных уровней на момент выбора ──
    def scout_selection_put(self, symbol, snapshot, now_ms):
        """Добавить/обновить закладку символа со СНИМКОМ точных уровней (snapshot = находка целиком)."""
        self.execute(
            "INSERT INTO scout_selections(symbol,ts,ts_ms,payload) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts, ts_ms=excluded.ts_ms, payload=excluded.payload",
            (symbol, _utcnow_iso(), int(now_ms), json.dumps(snapshot, ensure_ascii=False)))

    def scout_selection_remove(self, symbol):
        """Снять закладку символа."""
        self.execute("DELETE FROM scout_selections WHERE symbol=%s", (symbol,))

    def scout_selections_all(self):
        """Все закладки (list[dict]: symbol, ts, ts_ms, payload JSON-строка) — для показа + расчёта свежести."""
        return self.query("SELECT symbol, ts, ts_ms, payload FROM scout_selections ORDER BY ts_ms DESC", ())

    # ── управление сервисом-скаутом (под-шаг 4): кнопка + метки прогонов + heartbeat ──
    _SCOUT_CTRL_KEYS = ("scan_now_ms", "scan_now_ack_ms", "last_a_ms", "last_b_boundary_ms", "heartbeat_ms")

    def _scout_control_ensure(self):
        self.execute(
            "INSERT INTO scout_control(id,scan_now_ms,scan_now_ack_ms,last_a_ms,last_b_boundary_ms,heartbeat_ms,updated_ts) "
            "VALUES(1,0,0,0,0,0,%s) ON CONFLICT(id) DO NOTHING", (_utcnow_iso(),))

    def scout_control_get(self):
        """Состояние управления скаутом (int-поля; нули если строки нет). FAIL-SOFT."""
        try:
            rows = self.query("SELECT " + ",".join(self._SCOUT_CTRL_KEYS) + " FROM scout_control WHERE id=1", ())
            if not rows:
                return {k: 0 for k in self._SCOUT_CTRL_KEYS}
            return {k: int(rows[0].get(k) or 0) for k in self._SCOUT_CTRL_KEYS}
        except Exception:
            return {k: 0 for k in self._SCOUT_CTRL_KEYS}

    def scout_control_request_scan(self, now_ms):
        """Кнопка «Сканировать сейчас» (дашборд): durable-намерение scan_now_ms. Скаут потребит и заакает."""
        self._scout_control_ensure()
        self.execute("UPDATE scout_control SET scan_now_ms=%s, updated_ts=%s WHERE id=1", (int(now_ms), _utcnow_iso()))

    def scout_control_mark(self, **fields):
        """Скаут-сторона: targeted-обновление ack/last_a/last_b/heartbeat (без клоббера scan_now — дашборд-поле)."""
        allowed = ("scan_now_ack_ms", "last_a_ms", "last_b_boundary_ms", "heartbeat_ms")
        sets = [(k, int(v)) for k, v in fields.items() if k in allowed and v is not None]
        if not sets:
            return
        self._scout_control_ensure()
        cols = ", ".join(k + "=%s" for k, _ in sets)
        self.execute("UPDATE scout_control SET " + cols + ", updated_ts=%s WHERE id=1",
                     tuple(v for _, v in sets) + (_utcnow_iso(),))

    def scout_findings_log_put_many(self, rows, now_ms):
        """Append находок в журнал «что советовал» (пост-анализ, §O.8). id = MAX+1 (единственный писатель — скаут)."""
        if not rows:
            return 0
        ts = _utcnow_iso()
        base = self.query("SELECT COALESCE(MAX(id),0) AS m FROM scout_findings_log", ())[0]["m"]
        for k, r in enumerate(rows, 1):
            self.execute(
                "INSERT INTO scout_findings_log(id,ts,ts_ms,symbol,status,payload) VALUES(%s,%s,%s,%s,%s,%s)",
                (int(base) + k, ts, int(now_ms), r["symbol"], r.get("status"),
                 json.dumps(r, ensure_ascii=False)))
        return len(rows)

    def fillrate_counts(self):
        """Fill-rate за всё время: касаний теневого движка (signals.shadow_would_touch='yes') и реально
        залитых ног (fills). {'touches': int, 'filled': int}. Пусто до Вехи 5 -> нули."""
        t = self.query("SELECT COUNT(*) AS n FROM signals WHERE shadow_would_touch=%s", ("yes",))
        f = self.query("SELECT COUNT(*) AS n FROM fills", ())
        return {"touches": int(t[0]["n"]) if t else 0, "filled": int(f[0]["n"]) if f else 0}

    # ── WS-тень (Веха 5.2 п6, measure-first): write-only лог execution + разрывы, ВНЕ пути решений ──
    def ws_exec_put_many(self, rows):
        """Батч-вставка реальных execution-событий WS-тени в ws_exec_log. Идемпотентно по exec_id (UNIQUE +
        ON CONFLICT DO NOTHING) — reconnect-дубли и повторный дренаж не задваивают; дубли ВНУТРИ батча
        отсекаются в Python (keep-first, а также обходит PG-ограничение «row a second time» на мульти-VALUES).
        id=MAX(id)+1 берётся ОДИН раз на батч под self._lock (не на строку), как _append_row; retry-once при
        PK-коллизии id (единственный писатель — дренаж главного цикла, но конвенция кодовой базы). rows —
        list[dict] с ключами WS_EXEC_COLS (ts дефолт _utcnow_iso; is_foreign/is_backfilled дефолт 0).
        Возвращает число ВСТАВЛЕННЫХ строк (дубли не считаются). Батч-execute_values — перф-опция Стадии B."""
        if not rows:
            return 0
        seen, deduped = set(), []
        for r in rows:                                      # дедуп внутри батча по exec_id (keep-first)
            eid = r.get("exec_id")
            if eid is not None and eid in seen:
                continue
            if eid is not None:
                seen.add(eid)
            deduped.append(r)
        cols = WS_EXEC_COLS
        col_sql = ",".join(cols)
        placeholders = ",".join(["%s"] * (len(cols) + 1))   # +1 под id
        ins = (f"INSERT INTO ws_exec_log(id,{col_sql}) VALUES({placeholders}) "
               f"ON CONFLICT(exec_id) DO NOTHING")
        maxsql = "SELECT COALESCE(MAX(id),0)+1 FROM ws_exec_log"

        def _vals(r):
            out = []
            for c in cols:
                if c == "ts":
                    out.append(r.get("ts") or _utcnow_iso())
                elif c in ("is_foreign", "is_backfilled"):
                    out.append(int(r.get(c) or 0))
                else:
                    out.append(r.get(c))
            return out

        with self._lock:
            if self.is_pg:
                conn = self.pool.getconn()
                try:
                    for attempt in range(2):
                        try:
                            inserted = 0
                            with conn.cursor() as cur:
                                cur.execute(maxsql)
                                next_id = cur.fetchone()[0]
                                for i, r in enumerate(deduped):
                                    cur.execute(ins, (next_id + i, *_vals(r)))
                                    inserted += 1 if (cur.rowcount or 0) > 0 else 0
                            conn.commit()
                            return inserted
                        except self._integrity_err:
                            conn.rollback()             # конкурент занял id -> пересчитать MAX+1 и повторить раз
                            if attempt:
                                raise
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    self.pool.putconn(conn)
            else:
                ins_q = self._ph(ins)
                for attempt in range(2):
                    try:
                        next_id = self.conn.execute(maxsql).fetchone()[0]
                        inserted = 0
                        for i, r in enumerate(deduped):
                            cur = self.conn.execute(ins_q, (next_id + i, *_vals(r)))
                            inserted += 1 if (cur.rowcount or 0) > 0 else 0
                        self.conn.commit()
                        return inserted
                    except self._integrity_err:
                        self.conn.rollback()
                        if attempt:
                            raise

    def ws_gaps_put(self, *, gap_start_ms, gap_end_ms, backfilled=0):
        """Записать окно разрыва WS-стрима (append) — для честного знаменателя покрытия (Стадия B).
        backfilled=1 после REST-догона окна (под-шаг 7). Возвращает id."""
        return self._append_row("ws_gaps", {
            "ts": _utcnow_iso(), "gap_start_ms": int(gap_start_ms),
            "gap_end_ms": int(gap_end_ms), "backfilled": int(backfilled)})

    def ws_exec_all(self):
        """Все строки ws_exec_log по возрастанию id (Стадия B / тесты)."""
        return self.query("SELECT * FROM ws_exec_log ORDER BY id", ())

    def ws_exec_by_link(self, order_link_id):
        """Строки ws_exec_log по order_link_id, по возрастанию exec_time_ms."""
        return self.query(
            "SELECT * FROM ws_exec_log WHERE order_link_id=%s ORDER BY exec_time_ms", (order_link_id,))

    def ws_gaps_all(self):
        """Все окна разрыва WS по возрастанию id."""
        return self.query("SELECT * FROM ws_gaps ORDER BY id", ())


class WsExecFacade:
    """Узкий write-only фасад над DB для WS-тени (Веха 5.2 п6, measure-first). Физически НЕ имеет
    state_put/state_mutate/state_clear/mark_*/capital_*/execute/query — тень не может тронуть торговый путь
    через БД даже случайно (parity-safeguard, ADR 0014): тени передаётся ЭТОТ фасад, а не полный DB. Только
    ws_exec_put_many / ws_gaps_put. Структурный тест изоляции (под-шаг 6) дополнительно запрещает тени
    импортировать lifecycle/executor/store и обращаться к _db.<торговый метод>."""

    def __init__(self, db):
        self._db = db

    def ws_exec_put_many(self, rows):
        return self._db.ws_exec_put_many(rows)

    def ws_gaps_put(self, *, gap_start_ms, gap_end_ms, backfilled=0):
        return self._db.ws_gaps_put(gap_start_ms=gap_start_ms, gap_end_ms=gap_end_ms, backfilled=backfilled)
