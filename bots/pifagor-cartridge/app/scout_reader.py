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
from datetime import UTC, datetime

from app import mapper
from app.reader import _ensure_vendor_on_path


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
        import config.execution as _exec  # scout использует STOP_FIB отсюда (scan.py:72)
        from dashboard.viewmodel import build_scout, build_scout_chart  # ленивый импорт
        from storage.db import DB

        self._build_scout = build_scout
        self._build_scout_chart = build_scout_chart
        self.scout_db = DB(db_path=scout_db_path, owner=False)  # scout.db, singleton-lock НЕ берём
        self._worker = worker_reader
        self._scout_stop_fib = float(getattr(_exec, "STOP_FIB", 1.0))
        self._detector = detector_version
        self._producer = producer

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

    def findings_for_universe(self) -> tuple[int, list[dict]]:
        """Лёгкие находки для динамического провайдера (S8): (scan_ms, [{symbol,tf,state,score}]).
        Без klines/levels/ордеров — геометрия отбора для стека. scan_ms=0 → скаут ещё не сканил.
        Символы в верхнем регистре. Переиспользует build_scout (принцип #10)."""
        scan_ms = self._scan_cursor()
        if scan_ms == 0:
            return 0, []
        sv = self._build_scout(self.scout_db) or {}
        out = []
        for f in sv.get("findings") or []:
            sym = str(f.get("symbol") or "").strip().upper()
            if sym:
                out.append({"symbol": sym, "tf": f.get("tf") or "4h",
                            "state": f.get("state") or "", "score": f.get("score")})
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

    def build_snapshots(self) -> tuple[int, list[dict]]:
        """(scan_ms, список контрактных снимков). Пустой список = у скаута сейчас нет находок."""
        scan_ms = self._scan_cursor()          # триггер+scan_ts по scout_control, не по meta
        sv = self._build_scout(self.scout_db) or {}
        findings = sv.get("findings") or []
        if not findings:
            return scan_ms, []
        worker_eff = self._worker_eff()
        orders_by = self._orders_by_symbol()
        pos_by = self._positions_by_symbol()
        scan_iso = _iso_ms(scan_ms)
        orders_iso = datetime.now(UTC).isoformat()  # orders_ts = момент чтения книги движка
        out = []
        for f in findings:
            sym, tf = f.get("symbol"), f.get("tf") or "4h"
            chart = self._chart(sym, tf)                          # свечи скан-ТФ + сырая находка
            raw = chart.get("finding") or {}                     # A/B/entries/stop из payload
            merged = {**f, **raw}                                 # плоский вид + сырые уровни
            data_ms = self._data_upto_ms(sym, tf) or scan_ms
            out.append(mapper.scout_snapshot(
                merged, worker_eff=worker_eff, scout_stop_fib=self._scout_stop_fib,
                orders_raw=orders_by.get(sym), position=pos_by.get(sym),
                detector_version=self._detector, producer=self._producer,
                scan_ts_iso=scan_iso, orders_ts_iso=orders_iso, data_upto_iso=_iso_ms(data_ms),
                candles=chart.get("candles"), klines_tf=tf,       # klines_tf = tf сетапа
            ))
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
