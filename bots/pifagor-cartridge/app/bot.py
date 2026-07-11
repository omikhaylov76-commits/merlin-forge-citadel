"""Цикл картриджа Пифагора: heartbeat ≤60с + телеметрия из build_monitor + опрос команд (шов S4).

Отличие от эталона paper-bot — **4xx-классификация обязательна** (Куратор #6/#7):
  - транзиентный сбой пуша → ретрай с backoff; исчерпан → лог, курсор НЕ двигаем.
  - перманентный (401/403/422) → лог + пропуск батча (НЕ долбим ядро), курсор двигаем (poison).
  - 413 → дробим батч пополам рекурсивно (Контракт: «бот дробит»).

Курсоры trades/events двигаем ТОЛЬКО при не-транзиентном исходе → at-least-once (ядро дедупит).
Время разведено: now (стенное)→ts; mono (монотонное)→интервалы/uptime — инъектируются в tick_once
(тесты дают фиксированные последовательности). stop_close → латч kill-switch + встаём.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from app import mapper
from app.client import PayloadTooLarge, PermanentError, TransientError, send_with_backoff
from app.config import CONTRACT_VERSION, CartridgeConfig

log = logging.getLogger("mfc.pifagor-cartridge")


class PifagorCartridge:
    def __init__(self, client, reader, config: CartridgeConfig,
                 *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._client = client
        self._reader = reader
        self._cfg = config
        self._sleep = sleep
        self._start_mono: float | None = None
        self._last_hb_mono: float | None = None
        self._trade_cursor = 0
        self._event_cursor = 0

    def tick_once(self, now: datetime, mono: float) -> bool:
        """Одна итерация. Возвращает should_stop (True после stop_close)."""
        if self._start_mono is None:
            self._start_mono = mono
        monitor = self._reader.snapshot(now_ms=int(now.timestamp() * 1000))

        # heartbeat при наступлении времени (≤60с; кормит stale-скан часового)
        hb = self._cfg.heartbeat_interval_s
        if self._last_hb_mono is None or mono - self._last_hb_mono >= hb:
            status = mapper.heartbeat_status(monitor, paused=self._reader.is_paused())
            self._send(lambda: self._client.heartbeat(
                status=status, uptime_s=mono - self._start_mono, contract_version=CONTRACT_VERSION,
            ), "heartbeat")
            self._last_hb_mono = mono

        self._push_telemetry(monitor, now)
        return self._handle_command(now)

    def _push_telemetry(self, monitor: dict, now: datetime) -> None:
        # equity — точка за ts=now; дедуп ядром по (instance, ts). Сбой → новая точка на след. тике.
        self._send(lambda: self._client.push_equity(
            mapper.equity_point(monitor, ts_iso=now.isoformat())), "equity")
        # trades / events — курсор двигаем лишь при не-транзиентном исходе (at-least-once)
        trades, new_tc = mapper.trades_batch(monitor, after_id=self._trade_cursor)
        if not trades or self._push_batch(self._client.push_trades, trades, "trades"):
            self._trade_cursor = new_tc
        events, new_ec = mapper.events_batch(monitor, after_id=self._event_cursor)
        if not events or self._push_batch(self._client.push_events, events, "events"):
            self._event_cursor = new_ec

    def _handle_command(self, now: datetime) -> bool:
        try:
            resp = self._client.next_command(wait=self._cfg.poll_wait_s)
        except PermanentError as exc:
            log.error("commands/next: перманентный отказ (%s) — пропуск опроса", exc)
            return False
        except TransientError as exc:
            log.warning("commands/next: транзиент (%s) — пропуск, повтор на след. тике", exc)
            return False
        cmd, cmd_id = resp.get("cmd"), resp.get("cmd_id")
        if not cmd_id or cmd in (None, "none"):
            return False
        if cmd == "pause":
            self._reader.pause()  # честно: стоп входов, позиции держатся (PAUSE_ENABLED)
            self._ack(cmd_id, "ok")
            return False
        if cmd == "resume":
            self._reader.resume()
            self._ack(cmd_id, "ok")
            return False
        if cmd == "stop_close":
            # kill-switch латч (durable): движок гасит вход/флэттит под LIVE_TRADING
            self._reader.stop_close()
            # немедленный «stopping» heartbeat — видимость стопа в ядре даже без движка
            self._send(lambda: self._client.heartbeat(
                status="stopping", uptime_s=0.0, contract_version=CONTRACT_VERSION), "heartbeat")
            self._ack(cmd_id, "ok")
            return True  # встаём: цикл завершится, процесс выйдет (restartPolicy=never)
        # неизвестная команда — ack error (это не stop_close, липкость ядра тут не держит)
        self._ack(cmd_id, "error", {"reason": f"unknown:{cmd}"})
        return False

    # ── доставка с классификацией 4xx ─────────────────────────────────────────

    def _deliver(self, fn: Callable[[], None]) -> None:
        """send_with_backoff с параметрами конфига (единая точка ретрай-политики)."""
        send_with_backoff(fn, retries=self._cfg.telemetry_retries, base_s=self._cfg.backoff_base_s,
                          cap_s=self._cfg.backoff_cap_s, sleep=self._sleep)

    def _send(self, fn: Callable[[], None], label: str) -> bool:
        """Неделимый пуш. True = доставлено/недоставляемо; False = транзиент исчерпан."""
        try:
            self._deliver(fn)
            return True
        except PermanentError as exc:
            log.error("%s: перманентный отказ ядра (%s) — пропуск, не долблю", label, exc)
            return True
        except PayloadTooLarge as exc:
            log.error("%s: 413 на неделимом payload (%s) — пропуск", label, exc)
            return True
        except TransientError as exc:
            log.warning("%s: транзиент исчерпал ретраи (%s) — best-effort, дальше", label, exc)
            return False

    def _push_batch(self, push_fn: Callable[[list], None], items: list, label: str) -> bool:
        """Батч с дроблением на 413. True = доставлено/дропнуто (курсор); False = транзиент."""
        try:
            self._deliver(lambda: push_fn(items))
            return True
        except TransientError as exc:
            log.warning("%s: транзиент исчерпал ретраи (%s, n=%d) — позже", label, exc, len(items))
            return False
        except PermanentError as exc:
            log.error("%s: перманентный отказ (%s) — дроп батча n=%d", label, exc, len(items))
            return True
        except PayloadTooLarge:
            if len(items) <= 1:
                log.error("%s: 413 на одном элементе — дроп", label)
                return True
            mid = len(items) // 2
            left = self._push_batch(push_fn, items[:mid], label)
            right = self._push_batch(push_fn, items[mid:], label)
            return left and right

    def _ack(self, cmd_id: str, result: str, detail: dict | None = None) -> None:
        """ack с backoff по транзиенту (для stop_close ядро держит липкость до ok)."""
        try:
            self._deliver(
                lambda: self._client.ack_command(cmd_id=cmd_id, result=result, detail=detail))
        except (PermanentError, TransientError) as exc:
            log.error("ack(%s,%s): не доставлен (%s) — ядро повторит команду", cmd_id, result, exc)

    def run(self, stop: threading.Event) -> None:
        """Цикл до stop или stop_close. Сбой оборота — best-effort: лог + продолжить."""
        while not stop.is_set():
            try:
                if self.tick_once(datetime.now(UTC), time.monotonic()):
                    log.info("stop_close исполнен — картридж встаёт")
                    return
            except Exception:  # noqa: BLE001 — ядро/БД недоступны: картридж не роняем
                log.exception("оборот упал — best-effort, продолжаю")
            stop.wait(self._cfg.tick_interval_s)
        log.info("картридж остановлен")
