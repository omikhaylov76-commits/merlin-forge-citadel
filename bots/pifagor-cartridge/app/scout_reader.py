"""ScoutReader — read-only мост к состоянию СКАУТА вендоренного снимка (ADR-0016, #52).

Второй `DB(owner=False, db_path=scout.db)` — ОТДЕЛЬНАЯ scout.db (изоляция #51), НЕ воркерская БД.
Читаем через вью-модель `build_scout` (принцип #10, как build_monitor) + сырые находки
`scout_finding_get` (A/B/entries/stop — их плоский build_scout не отдаёт). Ордера/позицию/конфиг
берём из ВОРКЕРА (PifagorReader.db / .config_store) — они в БД движка, не скаута.

klines/klines_tf ОПУСКАЕМ: у скаута нет 15m/5m в Фазе 1 (ADR-0016 д). Несём геометрию levels.
Триггер пуша — новый курсор скана Этапа B/кнопки (см. _scan_cursor, #54), не каждый цикл.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime

from app import mapper
from app.reader import _ensure_vendor_on_path

log = logging.getLogger("mfc.pifagor-cartridge")


def _iso_ms(ms: int | None) -> str:
    if not ms:
        return datetime.now(UTC).isoformat()
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC).isoformat()


class ScoutReader:
    def __init__(
        self, *, scout_db_path: str, worker_reader, detector_version: str, producer: str,
    ) -> None:
        _ensure_vendor_on_path()
        import config as _vcfg  # vendor config: COINS_CONFIG нужен warm-гарду (classify:228)
        import config.execution as _exec  # scout использует STOP_FIB отсюда (scan.py:72)
        from dashboard.viewmodel import build_scout, build_scout_chart  # ленивый импорт
        from storage.db import DB
        from strategy import warm as _warm  # реплей сделки (F-scout-snap: реальная сетка held)

        self._build_scout = build_scout
        self._build_scout_chart = build_scout_chart
        self._vendor_cfg = _vcfg
        self._warm_classify = _warm.classify
        # database_url="" — ЯВНЫЙ пин на SQLite-файл скаута: с приходом DATABASE_URL (Postgres
        # воркера, 2026-07-21) vendor DB() предпочёл бы его пути файла → адаптер читал бы ПУСТЫЕ
        # scout-таблицы воркер-БД, а скаут писал бы в свой SQLite (живой баг: вселенная молчит).
        self.scout_db = DB(db_path=scout_db_path, owner=False, database_url="")
        self._worker = worker_reader
        self._scout_stop_fib = float(getattr(_exec, "STOP_FIB", 1.0))
        self._detector = detector_version
        self._producer = producer
        # Статичная вселенная ФИКС-бота (enabled COINS_CONFIG на буте) — для in_universe правды
        # движка, когда провайдера динамики нет. Снимок ДО любых setdefault-засевов _classify
        # (засев делает classify-гард проходимым для чужих монет и растёт по ходу — членством
        # в наборе движка он НЕ является).
        self._static_universe = frozenset(
            str(sym).upper() for sym, c in (_vcfg.strategy.COINS_CONFIG or {}).items()
            if isinstance(c, dict) and c.get("enabled")
        )

    def _scan_cursor(self) -> int:
        """Курсор последнего СКАНА СЕТАПОВ (Этап B / кнопка) из scout_control. last_a_ms исключён
        (#54): Этап A — калибровка вселенной без находок; его пуш пуст и «съедал» бы курсор
        (last_a_ms=сейчас > округлённой last_b_boundary_ms), из-за чего находки первого Этапа B
        ждали бы след. границы, а утренний Этап A обнулял бы доску. Мёртвые сетапы чистит Этап B."""
        try:
            c = self.scout_db.scout_control_get() or {}
            return max(
                int(c.get("last_b_boundary_ms") or 0),
                int(c.get("scan_now_ack_ms") or 0),
            )
        except Exception:  # noqa: BLE001
            return 0

    def last_scan_ms(self) -> int:
        """Курсор последнего скана (для триггера «пушить, если новый»)."""
        return self._scan_cursor()

    def scan_list_rows(self) -> list[dict]:
        """Курированный ПУЛ КАЧЕСТВА (vendor `scout_list_all`): монеты с ПУСТЫМИ hard_rejects
        (оборот/возраст≥90д/спред/история/не-стейбл — фильтры Оператора, Этап A `universe.py`) И
        скором качества ≥ порога. [{symbol, score}] по убыванию скора. Fail-soft [] (пул не
        прочитался → провайдер держит прежний набор). УСЛОВИЕ ПОДПИСИ: берём ТОЛЬКО отфильтрованный
        scout_list, НЕ сырой scout_universe_all — сито качества = защита от мусора."""
        try:
            out = []
            for r in self.scout_db.scout_list_all() or []:
                sym = str(r.get("symbol") or "").strip().upper()
                if sym:
                    out.append({"symbol": sym, "score": r.get("score")})
            return out
        except Exception:  # noqa: BLE001 — пул не прочитался → пусто (провайдер держит набор)
            log.exception("scan_list: чтение курированного пула упало — пул пуст")
            return []

    def placeable_scan(self) -> tuple[int, dict]:
        """F-lookahead v3 (подпись Куратора): движко-PLACEABLE отбор ИЗ пула качества scout_list —
        НЕ скаут-курация. Гоняет warm-реплей (`_classify`, ТА ЖЕ функция постановки) по каждой
        монете пула на свежих свечах кэша (Этап B докачал ВЕСЬ scout_list каждые 4h). Возврат:
        (scan_ms, {symbol: {kind, auto_eligible, reanchored, score}}) ТОЛЬКО для placeable
        (PENDING: самоход ставит auto, кнопка — reanchored; OPEN=в позиции/None → мимо). scan_ms —
        триггер провайдера (зеркало findings_for_universe). Замер длительности в лог."""
        scan_ms = self._scan_cursor()
        if scan_ms == 0:
            return 0, {}                      # скаут ещё не сканил — пула нет
        from app.dynamic_universe import _DEFAULT_COIN
        pool = self.scan_list_rows()
        t0 = time.monotonic()
        out: dict = {}
        for row in pool:
            sym = row["symbol"]
            # АДВЕРС-РЕВЬЮ: движок при dynamic берёт coins.json ЦЕЛИКОМ (REPLACE, strategy.py:125)
            # с _DEFAULT_COIN. Форсим ТЕ ЖЕ пороги (не унаследованные mb статик-вендора вроде
            # AAVE 2.5/4.0 — иначе вердикт адаптера разойдётся с постановкой движка).
            self._vendor_cfg.strategy.COINS_CONFIG[sym] = dict(_DEFAULT_COIN)
            ok, desc = self._classify(sym)
            if not ok or desc is None:
                continue
            if str(desc.get("kind")) != "PENDING":   # OPEN (в рынке) / None — не свежая постановка
                continue
            out[sym] = {"kind": "PENDING", "auto_eligible": bool(desc.get("auto_eligible")),
                        "reanchored": bool(desc.get("reanchored")), "score": row.get("score")}
        log.info("scout: placeable-скан пула %d → годных %d за %.2fс",
                 len(pool), len(out), time.monotonic() - t0)
        return scan_ms, out

    def findings_for_universe(self) -> tuple[int, list[dict]]:
        """Лёгкие находки для динамического провайдера (S8): (scan_ms, [{symbol,tf,state,score,
        bars_since_anchor}]). Без klines/levels — геометрия отбора для стека. `bars_since_anchor` —
        возраст сетапа в барах (уже в build_scout) для фильтра свежести ADR-0020 (0 vendor — только
        дочитываем). scan_ms=0 → скаут ещё не сканил. Символы в верхнем регистре."""
        scan_ms = self._scan_cursor()
        if scan_ms == 0:
            return 0, []
        sv = self._build_scout(self.scout_db) or {}
        out = []
        for f in sv.get("findings") or []:
            sym = str(f.get("symbol") or "").strip().upper()
            if sym:
                # ВЕНДОР build_scout кладёт стадию под ключом "status" (viewmodel:542), НЕ "state";
                # маппим в "state" (как рабочий mapper:265). Читать "state" = всегда None
                # → стек пуст → фича немая (мок маскировал; тест ниже — против вендора).
                out.append({"symbol": sym, "tf": f.get("tf") or "4h",
                            "state": f.get("status") or "", "score": f.get("score"),
                            "bars_since_anchor": f.get("bars_since_anchor")})
        return scan_ms, out

    def scan_now(self, *, now_ms: int) -> None:
        """Кнопка «Сканировать сейчас» (Разведка-стол): durable-намерение через ВЕНДОРСКИЙ канал
        кнопки `scout_control_request_scan` (db.py:1247, дашборд-сторона). НЕ `scout_control_mark`:
        тот — «скаут-сторона» с whitelist БЕЗ scan_now_ms, чужие ключи МОЛЧА дропает (db.py:1254-57)
        — живой Галахад это показал: ack ok, а Этап B не стартует. Вендор на след. wake-loop видит
        scan_now_ms > scan_now_ack_ms (main.py:160) → Этап B(button) → ачит ack=scan_now_ms."""
        self.scout_db.scout_control_request_scan(int(now_ms))

    def force_recalibrate(self) -> None:
        """Принудительная перекалибровка списка (Разведка-стол, dozor_apply): сброс last_a_ms=0 →
        вендорский decide() на след. тике даёт ('A','bootstrap') → Этап A пересоберёт scout_list на
        НОВЫХ порогах отбора. Без этого рестарт грузит новый env, но при живом списке decide()
        пропускает Этап A (main.py:158) → скан на СТАРОМ списке = «применил, а разницы нет».
        Вендорский `mark` (last_a_ms в whitelist; targeted UPDATE, scan_now не клоббер)."""
        self.scout_db.scout_control_mark(last_a_ms=0)

    def _classify(self, symbol: str) -> tuple[bool, dict | None]:
        """warm-реплей символа на 4h-свечах кэша скаута → (посчиталось, дескриптор|None).

        Трёхзначно — правде движка нужна разница «вердикта нет» и «вердикт неизвестен»:
          (True, dict)  — активный сетап (PENDING/OPEN, факты для engine-поля);
          (True, None)  — ЧЕСТНЫЙ вердикт «активного сетапа нет» (реплей закрыл / нет пробоя);
          (False, None) — посчитать не вышло (мало свечей / сбой) → снимок БЕЗ engine-поля.
        `strategy.warm.classify` — ТА ЖЕ функция, что решает постановку движком (самоход/кнопка).
        COINS_CONFIG-гард: символ вне конфига до-вписываем дефолтом динамики (in-memory этого
        процесса; vendor-код не трогается) — иначе classify-гард молча даст None на чужой монете."""
        try:
            rows = self.scout_db.scout_klines_read_window(symbol, "4h", 300) or []
            if len(rows) < 60:                    # короткая серия → реплей недостоверен
                return False, None
            import numpy as np
            o = np.array([float(r["open"]) for r in rows])
            h = np.array([float(r["high"]) for r in rows])
            low = np.array([float(r["low"]) for r in rows])
            c = np.array([float(r["close"]) for r in rows])
            t4 = np.array([int(r["time"]) for r in rows], dtype=np.int64)
            from app.dynamic_universe import _DEFAULT_COIN  # един. источник дефолт-блока динамики
            self._vendor_cfg.strategy.COINS_CONFIG.setdefault(symbol, dict(_DEFAULT_COIN))
            return True, self._warm_classify(o, h, low, c, t4, symbol)
        except Exception:  # noqa: BLE001 — реплей упал → «неизвестно», телеметрию не роняем
            log.exception("warm-реплей %s упал — снимок без правды движка", symbol)
            return False, None

    def _verified_grid(self, symbol: str) -> dict | None:
        """Реальная сетка сделки held-символа (F-scout-snap): дескриптор реплея либо None
        (не посчиталось ИЛИ активного сетапа нет — честно без сетки, не выдумываем)."""
        ok, desc = self._classify(symbol)
        return desc if ok else None

    def _truth(
        self, symbol: str, universe: frozenset[str] | None,
    ) -> tuple[bool, dict | None, dict | None]:
        """(посчиталось, дескриптор, engine-поле) ОДНИМ реплеем — held-снимку нужны и сетка,
        и правда движка; двойной прогон classify на монету был бы вдвое дороже зря.
        universe — стек динамики (провайдер); None → статичная вселенная фикс-бота (бут-снимок)."""
        ok, desc = self._classify(symbol)
        if not ok:
            return False, None, None
        pool = universe if universe is not None else self._static_universe
        return True, desc, mapper.engine_truth(desc, in_universe=symbol.upper() in pool)

    @staticmethod
    def _apply_grid(merged: dict, grid: dict) -> None:
        """Переписать теорию скаута РЕАЛЬНОЙ сеткой движка (A/B/входы/стоп). Ключи entries —
        строки (как после JSON: scout_levels читает '0.382'/'0.5'/'0.618')."""
        merged["A"], merged["B"], merged["stop"] = grid["A"], grid["B"], grid["stop"]
        merged["entries"] = {str(k): v for k, v in (grid.get("entries") or {}).items()}

    def build_snapshots(
        self, held: frozenset[str] = frozenset(), universe: frozenset[str] | None = None,
    ) -> tuple[int, list[dict]]:
        """(scan_ms, список контрактных снимков). Пустой список = у скаута сейчас нет находок.

        held (F-scout-snap, S8): символы с живой позицией/ордером. Для них: (а) уровни находки
        ЗАМЕНЯЮТСЯ реальной сеткой сделки (warm-реплей) + verified=true; (б) если скаут символ
        уже НЕ отслеживает (committed ушёл из находок) — снимок СИНТЕЗИРУЕТСЯ (сетка + живые
        ордера/позиция + свечи из кэша), чтобы график не пропадал ровно когда позиция открыта.

        universe (S8 единая Разведка): рабочий набор движка (стек динамики; None → статичная
        вселенная фикс-бота). КАЖДАЯ 4h-находка получает поле `engine` (правда движка: тот же
        warm-реплей, что решает постановку) — доска-по-вердикту консоли строится из этих фактов.
        Реплей не посчитался → снимок без engine («неизвестно» ≠ «не берёт»)."""
        scan_ms = self._scan_cursor()          # триггер+scan_ts по scout_control, не по meta
        sv = self._build_scout(self.scout_db) or {}
        findings = sv.get("findings") or []
        if not findings and not held:
            return scan_ms, []
        worker_eff = self._worker_eff()
        orders_by = self._orders_by_symbol()
        pos_by = self._positions_by_symbol()
        scan_iso = _iso_ms(scan_ms)
        orders_iso = datetime.now(UTC).isoformat()  # orders_ts = момент чтения книги движка
        out = []
        seen_4h: set[str] = set()
        t_truth = time.monotonic()
        for f in findings:
            sym, tf = f.get("symbol"), f.get("tf") or "4h"
            chart = self._chart(sym, tf)                          # свечи скан-ТФ + сырая находка
            raw = chart.get("finding") or {}                     # A/B/entries/stop из payload
            merged = {**f, **raw}                                 # плоский вид + сырые уровни
            verified = False
            engine = None
            if tf == "4h":                     # правда движка — только торговый ТФ (SIGNAL_TF)
                ok, desc, engine = self._truth(sym, universe)
                if sym in held:
                    if ok and desc is not None:
                        self._apply_grid(merged, desc)    # график = сетка сделки, не догадка
                        verified = True
                    seen_4h.add(sym)
            data_ms = self._data_upto_ms(sym, tf) or scan_ms
            out.append(mapper.scout_snapshot(
                merged, worker_eff=worker_eff, scout_stop_fib=self._scout_stop_fib,
                orders_raw=orders_by.get(sym), position=pos_by.get(sym),
                detector_version=self._detector, producer=self._producer,
                scan_ts_iso=scan_iso, orders_ts_iso=orders_iso, data_upto_iso=_iso_ms(data_ms),
                candles=chart.get("candles"), klines_tf=tf,       # klines_tf = tf сетапа
                verified=verified, engine=engine,
            ))
        for sym in sorted(held - seen_4h):     # held без 4h-находки → синтез (график не пропадает)
            ok, desc, engine = self._truth(sym, universe)
            chart = self._chart(sym, "4h")
            fake: dict = {"symbol": sym, "tf": "4h", "status": "tracking", "score": 0}
            if ok and desc is not None:
                self._apply_grid(fake, desc)
            data_ms = self._data_upto_ms(sym, "4h") or scan_ms
            out.append(mapper.scout_snapshot(
                fake, worker_eff=worker_eff, scout_stop_fib=self._scout_stop_fib,
                orders_raw=orders_by.get(sym), position=pos_by.get(sym),
                detector_version=self._detector, producer=self._producer,
                scan_ts_iso=scan_iso, orders_ts_iso=orders_iso, data_upto_iso=_iso_ms(data_ms),
                candles=chart.get("candles"), klines_tf="4h",
                verified=ok and desc is not None, engine=engine,
            ))
        # Замер прохода правды движка (план слоя 1): десятки монет × numpy-реплей — должен быть
        # дёшев; если на живом станет дорого, увидим в логе, не гадая.
        log.info("scout: снимков %d, правда движка за %.2fс", len(out), time.monotonic() - t_truth)
        return scan_ms, out

    def _chart(self, symbol, tf) -> dict:
        """Свечи скан-ТФ (≤300 баров окна скана) из кэша скаута + сырая находка (read-only)."""
        try:
            return self._build_scout_chart(self.scout_db, symbol, tf=tf, n=300) or {}
        except Exception:  # noqa: BLE001 — нет свечей/находки → снимок без klines (валиден)
            return {}

    # ── чтение воркера (БД движка) — best-effort, телеметрию не роняем ──────────

    def _worker_eff(self) -> dict:
        try:
            return dict(self._worker.config_store.effective())
        except Exception:  # noqa: BLE001 — конфиг не прочитался: сравним с пустым (всё в mismatch)
            return {}

    def _data_upto_ms(self, symbol, tf) -> int:
        try:
            return int(self.scout_db.scout_klines_last_ms(symbol, tf) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def _orders_by_symbol(self) -> dict:
        out: dict = {}
        try:
            for row in self._worker.db.orders_open_all() or []:
                sym = row.get("symbol")
                payload = json.loads(row.get("payload") or "{}")
                legs = [{**leg, "side": payload.get("side")} for leg in payload.get("legs") or []]
                if legs:
                    out[sym] = legs
        except Exception:  # noqa: BLE001 — нет книги/битый payload → без ордеров (dry-run норма)
            pass
        return out

    def _positions_by_symbol(self) -> dict:
        out: dict = {}
        try:
            acct = self._worker.db.account_get() or {}
            positions = acct.get("positions")
            if isinstance(positions, str):
                positions = json.loads(positions or "[]")
            for p in positions or []:
                if p.get("symbol"):
                    out[p["symbol"]] = p
        except Exception:  # noqa: BLE001
            pass
        return out

    def close(self) -> None:
        closer = getattr(self.scout_db, "close", None)
        if callable(closer):
            closer()
