"""Сигнальный журнал (порция №3, Этап 1 переката 1-to-N) — деривер событий из worker-БД движка.

ЧИСТЫЙ НАБЛЮДАТЕЛЬ (0-vendor): курсорный direct-read журнальных таблиц движка
(signals/fills/events/closed_trades) по монотонному `id` → типизированные события Контракта
(`telemetry-signal-journal.schema.json`) → push в ядро. Торговлю НЕ меняет, вендор НЕ трогаем.

Идемпотентность (Куратор, вариант A): дедуп ЯДРОМ по натуральному ключу движка
(instance, src.table, src.id) — id строк worker-БД стабильны/монотонны (MAX(id)+1 под локом,
журнальные таблицы не прунятся) → пере-деривация после рестарта даёт ТЕ ЖЕ ключи → DO NOTHING.
Курсоры здесь — ОПТИМИЗАЦИЯ (не перечитывать), НЕ условие корректности. `seq` — порядок повтора
для диспетчера Этапа 2 (resume из ядра), не ключ дедупа.

GUARD ЭПОХИ БД (Куратор, fingerprint — обязателен): ядро хранит per-table последний (src_id, ts).
На бооте перечитываем строку id=src_id и СРАВНИВАЕМ ts (дериватор ts — та же функция, что писала):
строки нет ИЛИ ts не совпал → БД движка обнулилась (SQLite-фолбэк / ре-провижн Postgres) →
натуральные ключи новой эпохи КОЛЛИДИРУЮТ со старой (умерли бы как «дубли») → PARKED (fail-closed):
журнал встаёт, событие `journal_epoch_reset` (src.table="adapter", id=unix-ms — синтетика вне строк
движка), громкий алярм. Разбор эпохи — человеком. Остальная телеметрия картриджа живёт.

Схема событий и маппинг (подпись Куратора, сверка по вендор-коду П1–П4):
  signals → setup_detected (вкл. cap-фильтр/dry-run; mb/tf движок НЕ пишет → блок data.adapter);
  events:setup_placed → setup_placed (диспетчер повторяет ТОЛЬКО это);
  fills → leg_filled (requested_* — опросный путь движка, exec НЕ обещаем, П3);
  events:leg_exit → leg_exit; events:setup_closed(+reason из detail, П2)/close_all → setup_ended;
  closed_trades → trade_closed (реальный P&L Bybit);
  ПРОЧИЕ events (kill_switch_stop/warm_apply/idle_gap/worker_boot/orphan_*/ws_shadow_*/…) →
  service с raw-именем (П1: НИЧЕГО не дропаем — курсор мимо строки = потеря навсегда).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime

from app.client import CoreError, TransientError

log = logging.getLogger("mfc.pifagor-cartridge")

SCHEMA_VERSION = 1
_TABLES = ("signals", "fills", "events", "closed_trades")
# Порядок таблиц при равном ts (причинность: детект → событие/постановка → залив → финал).
_RANK = {"signals": 0, "events": 1, "fills": 2, "closed_trades": 3}
# Батч Контракта = schema maxItems = ядро _MAX_BATCH (telemetry-signal-journal.schema.json).
_CONTRACT_MAX_BATCH = 500
# Строк с одной таблицы за тик. Суммарно ≤ len(_TABLES)*_BATCH_PER_TABLE = _CONTRACT_MAX_BATCH:
# 413 из _collect НЕДОСТИЖИМ; бэклог дренится порциями за неск. тиков (курсор двигается лосслесс).
_BATCH_PER_TABLE = _CONTRACT_MAX_BATCH // len(_TABLES)   # 500 // 4 = 125
_UNKNOWN = "unknown"            # суффикс setup_id: якорь-сигнал вне наблюдения (курсор старше)


def _iso(ts_raw, fallback_ms=None) -> str:
    """ts строки движка → RFC3339 UTC. Приоритет: ISO-строка воркера → epoch-мс → 'сейчас'.
    ДЕТЕРМИНИРОВАН (одна строка → один ts) — на этом стоит fingerprint-guard эпохи."""
    if ts_raw:
        try:
            dt = datetime.fromisoformat(str(ts_raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.isoformat()
        except ValueError:
            pass
    if fallback_ms:
        try:
            return datetime.fromtimestamp(int(fallback_ms) / 1000, tz=UTC).isoformat()
        except (TypeError, ValueError, OSError):
            pass
    return datetime.now(UTC).isoformat()


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _detail_str(raw) -> str | None:
    return None if raw is None else str(raw)[:500]


def _setup_id(sym: str, bt) -> str:
    """setup_id = {symbol}:{bar_time}. Нечисловой/пустой bar_time → :unknown (деривацию НЕ роняем —
    иначе одна кривая строка заклинила бы весь журнал)."""
    if not bt:
        return f"{sym}:{_UNKNOWN}"
    try:
        return f"{sym}:{int(bt)}"
    except (TypeError, ValueError):
        return f"{sym}:{_UNKNOWN}"


class SignalJournalDeriver:
    """Держит курсоры/active-сетапы в памяти; корректность несёт натуральный ключ (не состояние)."""

    def __init__(self, reader, client, *, core_label: str, now_ms=None) -> None:
        self._db = reader.db                 # вендоренная DB (owner=False, лок движка не берём)
        self._client = client
        self._core = core_label
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cursors: dict[str, int] = dict.fromkeys(_TABLES, 0)
        self._seq = 0
        self._detected: dict[str, str] = {}  # symbol → setup_id последнего детекта (signals)
        self._active: dict[str, str] = {}    # symbol → setup_id активного placed-сетапа
        self._state = "init"                 # init → ready | parked (эпоха сменилась, fail-closed)

    # ── boot: резюм из ядра + fingerprint-guard эпохи ─────────────────────────

    def boot(self) -> bool:
        """Резюм курсоров/seq из ядра + сверка эпохи БД. False → parked/ретрай следующим тиком.
        Различаем: строки НЕТ/ts разошёлся → эпоха (park, fail-closed); СБОЙ чтения → ретрай."""
        try:
            cur = self._client.get_signal_journal_cursor()
        except Exception as exc:  # noqa: BLE001 — ядро недоступно: попробуем на след. тике
            log.warning("журнал: курсор из ядра не получен (%s) — boot отложен", exc)
            return False
        self._seq = int(cur.get("max_seq") or 0)
        for tbl, fp in (cur.get("tables") or {}).items():
            if tbl not in _TABLES:
                continue                      # adapter-синтетика курсором не является
            src_id = int(fp.get("src_id") or 0)
            try:
                row = self._row_by_id(tbl, src_id)
            except Exception as exc:  # noqa: BLE001 — транзиент чтения ≠ эпоха: ретрай, БЕЗ park
                log.warning("журнал: probe %s id=%d упал (%s) — boot отложен (без park)",
                            tbl, src_id, exc)
                return False
            if row is None or not self._ts_match(tbl, row, fp.get("ts")):
                self._park(tbl, src_id)
                return False
            self._cursors[tbl] = src_id
        self._seed_active()
        self._state = "ready"
        log.info("журнал: boot ok (seq=%d, курсоры=%s)", self._seq, self._cursors)
        return True

    def _row_by_id(self, table: str, row_id: int) -> dict | None:
        """Строка id=row_id, или None если её НЕТ (эпоха сменилась). Сбой запроса НЕ глушим —
        пусть всплывёт в boot: транзиент чтения ≠ смена эпохи (иначе ложный бессрочный park)."""
        if row_id <= 0:
            return {}                        # пустой курсор — эпоху сверять не с чем, легально
        rows = self._db.query(
            f"SELECT * FROM {table} WHERE id=%s", (row_id,)  # noqa: S608 — имя из _TABLES
        )
        return rows[0] if rows else None

    def _ts_match(self, table: str, row: dict, stored_iso) -> bool:
        if not row:
            return True                      # пустой курсор (src_id=0)
        derived = self._row_ts(table, row)
        try:
            a = datetime.fromisoformat(str(derived))
            b = datetime.fromisoformat(str(stored_iso))
            return abs((a - b).total_seconds()) <= 0.001
        except (TypeError, ValueError):
            return False

    def _park(self, table: str, src_id: int) -> None:
        """Эпоха БД сменилась → fail-closed: журнал встаёт, алярм + синтетика journal_epoch_reset.
        Курсоры НЕ двигаем, деривацию НЕ продолжаем (натуральные ключи эпох коллидируют)."""
        self._state = "parked"
        log.error("журнал: ЭПОХА БД СМЕНИЛАСЬ (%s: строка id=%d исчезла/ts разошёлся) — журнал "
                  "ВСТАЛ (fail-closed), нужен разбор человеком", table, src_id)
        try:
            self._client.push_signal_journal([{
                "schema_version": SCHEMA_VERSION, "core": self._core, "seq": self._seq + 1,
                "ts": datetime.now(UTC).isoformat(), "setup_id": f"-:{_UNKNOWN}",
                "kind": "service",
                "src": {"table": "adapter", "id": self._now_ms()},
                "data": {"raw": "journal_epoch_reset", "table": table, "probe_src_id": src_id},
            }])
        except Exception:  # noqa: BLE001
            log.exception("журнал: пуш journal_epoch_reset не прошёл (алярм остаётся в логе)")

    def _seed_active(self) -> None:
        """Посев active-сетапов из снимка setup_state движка (bar_time из payload карточки) —
        чтобы fills/exits, случившиеся до нашего наблюдения, легли на верный setup_id."""
        try:
            rows = self._db.query("SELECT symbol, payload FROM setup_state", ())
        except Exception:  # noqa: BLE001
            log.exception("журнал: посев setup_state упал — active пуст (unknown-суффикс)")
            return
        for r in rows or []:
            sym = str(r.get("symbol") or "").strip().upper()
            if not sym:
                continue
            try:
                payload = json.loads(r.get("payload") or "{}")
            except (TypeError, ValueError):
                payload = {}
            self._active[sym] = _setup_id(sym, payload.get("bar_time"))

    # ── tick: новые строки → события → push ───────────────────────────────────

    def tick(self) -> None:
        """Один оборот журнала (best-effort, вызывается из цикла картриджа)."""
        if self._state == "parked":
            return
        if self._state == "init" and not self.boot():
            return
        batch, advances = self._collect()
        if not batch:
            return
        try:
            self._client.push_signal_journal(batch)
        except TransientError as exc:  # сеть/5xx/429 — повтор следующим тиком, курсор стоит
            log.warning("журнал: пуш %d событий транзиент (%s) — повтор позже", len(batch), exc)
            return
        except CoreError as exc:
            # перманент/413: НЕ само-лечится. Громкий алярм; курсор НЕ двигаем (advance-and-drop
            # = потеря, журнал того не терпит) → журнал ждёт повтора и разбора человеком.
            log.error("журнал: пуш %d событий ОТКАЗ ядра (%s) — журнал ждёт (без потери)",
                      len(batch), exc)
            return
        self._cursors.update(advances)
        self._seq += len(batch)
        log.info("журнал: +%d событий (seq→%d)", len(batch), self._seq)

    def _collect(self) -> tuple[list[dict], dict[str, int]]:
        """Новые строки всех таблиц (id>курсор) → события в порядке (ts, причинность, id)."""
        rows: list[tuple[str, dict]] = []
        advances: dict[str, int] = {}
        for tbl in _TABLES:
            try:
                got = self._db.query(
                    f"SELECT * FROM {tbl} WHERE id>%s ORDER BY id LIMIT %s",  # noqa: S608
                    (self._cursors[tbl], _BATCH_PER_TABLE),
                )
            except Exception:  # noqa: BLE001
                log.exception("журнал: чтение %s упало — пропуск таблицы в этом тике", tbl)
                continue
            for r in got or []:
                rows.append((tbl, r))
            if got:
                advances[tbl] = int(got[-1]["id"])
        if not rows:
            return [], {}
        rows.sort(key=lambda tr: (self._row_ts(tr[0], tr[1]), _RANK[tr[0]], int(tr[1]["id"])))
        batch = []
        seq = self._seq
        for tbl, row in rows:
            seq += 1
            batch.append(self._event(tbl, row, seq))
        return batch, advances

    @staticmethod
    def _row_ts(table: str, row: dict) -> str:
        if table == "closed_trades":
            return _iso(None, fallback_ms=row.get("created_ms")) if row.get("created_ms") \
                else _iso(row.get("ts"))
        return _iso(row.get("ts"))

    # ── деривация одного события ──────────────────────────────────────────────

    def _event(self, table: str, row: dict, seq: int) -> dict:
        sym = str(row.get("symbol") or "").strip().upper()
        kind, setup_id, data = self._derive(table, row, sym)
        return {
            "schema_version": SCHEMA_VERSION, "core": self._core, "seq": seq,
            "ts": self._row_ts(table, row), "setup_id": setup_id[:80], "kind": kind,
            "src": {"table": table, "id": int(row["id"])},
            "data": data,
        }

    def _derive(self, table: str, row: dict, sym: str) -> tuple[str, str, dict]:
        if table == "signals":
            bt = row.get("bar_time")
            setup_id = _setup_id(sym, bt)
            self._detected[sym] = setup_id
            data = {
                "symbol": sym, "side": row.get("side"),
                "a": _num(row.get("a")), "b": _num(row.get("b")), "stop": _num(row.get("stop")),
                "entries": {"0.382": _num(row.get("entry_0382")), "0.5": _num(row.get("entry_05")),
                            "0.618": _num(row.get("entry_0618"))},
                "targets": {"0.382": _num(row.get("tgt_0382")), "0.5": _num(row.get("tgt_05")),
                            "0.618": _num(row.get("tgt_0618"))},
                "bar_time": bt,
                # П4: mb/tf движок в signals НЕ пишет — обогащение адаптера (честный провенанс)
                "adapter": self._adapter_enrich(sym),
            }
            return "setup_detected", setup_id, data

        if table == "fills":
            setup_id = self._setup_for(sym)
            data = {
                "symbol": sym, "side": row.get("side"), "entry_level": row.get("entry_level"),
                # П3: опросный путь движка — ЗАПРОШЕННЫЕ цена/объём, exec НЕ обещаем (NULL у движка)
                "requested_price": _num(row.get("requested_price")),
                "requested_qty": _num(row.get("requested_qty")),
                "order_id": row.get("order_id"), "order_link_id": row.get("order_link_id"),
            }
            return "leg_filled", setup_id, data

        if table == "closed_trades":
            setup_id = self._setup_for(sym)
            data = {
                "symbol": sym, "side": row.get("side"), "qty": _num(row.get("qty")),
                "avg_entry": _num(row.get("avg_entry")), "avg_exit": _num(row.get("avg_exit")),
                "closed_pnl": _num(row.get("closed_pnl")), "order_id": row.get("order_id"),
            }
            return "trade_closed", setup_id, data

        # events — по алфавиту вендора (П1: незнакомое → service, ничего не дропаем)
        ev = str(row.get("event") or "").strip()
        if ev == "setup_placed":
            setup_id = self._detected.get(sym) or self._setup_for(sym)
            self._active[sym] = setup_id
            data = {"symbol": sym, "detail": _detail_str(row.get("detail"))}
            return "setup_placed", setup_id, data
        if ev == "leg_exit":
            data = {
                "symbol": sym, "role": row.get("role"), "lv": _num(row.get("lv")),
                "qty": _num(row.get("qty")), "exit_link": row.get("exit_link"),
                "order_id": row.get("order_id"),
            }
            return "leg_exit", self._setup_for(sym), data
        if ev in ("setup_closed", "close_all") and sym and sym != "ALL":
            detail = _detail_str(row.get("detail"))
            reason = "timeout" if (detail and "timeout" in detail.lower()) else \
                ("close_all" if ev == "close_all" else "complete")   # П2: reason из detail
            setup_id = self._active.pop(sym, None) or self._setup_for(sym)
            return "setup_ended", setup_id, {"symbol": sym, "reason": reason, "detail": detail}
        # catch-all (kill_switch_stop / warm_apply / idle_gap / worker_boot / orphan_* /
        # ws_shadow_* / close_all[ALL] / будущие) — service с raw-именем
        return "service", self._setup_for(sym), {
            "symbol": sym or None, "raw": ev[:80], "detail": _detail_str(row.get("detail")),
        }

    def _setup_for(self, sym: str) -> str:
        if not sym or sym == "ALL":
            return f"-:{_UNKNOWN}"
        return self._active.get(sym) or self._detected.get(sym) or f"{sym}:{_UNKNOWN}"

    @staticmethod
    def _adapter_enrich(sym: str) -> dict:
        """mb per-coin из вселенной движка + tf из SIGNAL_TF — provenance: adapter (П4)."""
        out: dict = {"tf": os.environ.get("SIGNAL_TF", "4h"), "provenance": "adapter"}
        try:
            import config as vendor_config
            cfg = vendor_config.strategy.COINS_CONFIG.get(sym) or {}
            if cfg.get("mb1") is not None:
                out["mb1"] = _num(cfg.get("mb1"))
            if cfg.get("mb2") is not None:
                out["mb2"] = _num(cfg.get("mb2"))
        except Exception:  # noqa: BLE001 — обогащение best-effort, событие важнее
            pass
        return out
