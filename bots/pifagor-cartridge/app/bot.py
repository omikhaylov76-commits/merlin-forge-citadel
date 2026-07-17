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
                 *, sleep: Callable[[float], None] = time.sleep, scout_reader=None) -> None:
        self._client = client
        self._reader = reader
        self._cfg = config
        self._sleep = sleep
        self._scout = scout_reader          # None → scout-канал выключен (scout.db нет; флот)
        self._start_mono: float | None = None
        self._last_hb_mono: float | None = None
        self._last_scout_mono: float | None = None
        self._last_scan_ms = 0
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
            # каденцию сдвигаем ТОЛЬКО при успехе: провал → следующий тик ретраит (не ждём полный
            # интервал — иначе при MF_HEARTBEAT_S≈60 один провал пробил бы 60с-дедлайн Контракта)
            if self._send(lambda: self._client.heartbeat(
                status=status, uptime_s=mono - self._start_mono, contract_version=CONTRACT_VERSION,
            ), "heartbeat"):
                self._last_hb_mono = mono

        self._push_telemetry(monitor, now)
        self._push_scout(mono)
        return self._handle_command(now, mono)

    def _push_scout(self, mono: float) -> None:
        """Пуш scout-снимка при НОВОМ scan_ts (не каждый цикл; сканы редки). Отдельная scout.db.
        Пустой набор → пушим (replace: сетапы исчезли → ядро чистит). scout выключен → no-op."""
        if self._scout is None:
            return
        iv = self._cfg.scout_interval_s
        if self._last_scout_mono is not None and mono - self._last_scout_mono < iv:
            return
        self._last_scout_mono = mono
        try:
            scan_ms, snaps = self._scout.build_snapshots()
        except Exception:  # noqa: BLE001 — scout.db недоступна/битая → пропуск, цикл не роняем
            log.exception("scout: сбор снимков упал — пропуск")
            return
        if scan_ms == 0:
            return                                          # скаут ещё не сканировал — нечего слать
        if scan_ms <= self._last_scan_ms and self._last_scan_ms != 0:
            return                                          # не новый скан — не долбим ядро
        if self._send(lambda: self._client.push_scout(snaps), "scout"):
            self._last_scan_ms = scan_ms

    def _push_telemetry(self, monitor: dict, now: datetime) -> None:
        # equity — точка за ts=now; дедуп ядром по (instance, ts). Сбой → новая точка на след. тике.
        self._send(lambda: self._client.push_equity(
            mapper.equity_point(monitor, ts_iso=now.isoformat())), "equity")
        # engine_state — компакт факт-слоя для карточки бота (replace-снимок, каждый тик, дёшево)
        self._send(lambda: self._client.push_engine_state(
            mapper.engine_state(monitor)), "engine_state")
        # trades / events — курсор двигаем лишь при не-транзиентном исходе (at-least-once)
        prev_tc = self._trade_cursor
        trades, new_tc = mapper.trades_batch(monitor, after_id=prev_tc)
        if not trades or self._push_batch(self._client.push_trades, trades, "trades"):
            self._trade_cursor = new_tc
            self._warn_scroll_gap("trades", prev_tc, new_tc, mapper.TRADES_WINDOW)
        prev_ec = self._event_cursor
        events, new_ec = mapper.events_batch(monitor, after_id=prev_ec)
        if not events or self._push_batch(self._client.push_events, events, "events"):
            self._event_cursor = new_ec
            self._warn_scroll_gap("events", prev_ec, new_ec, mapper.EVENTS_WINDOW)

    @staticmethod
    def _warn_scroll_gap(label: str, prev: int, new: int, window: int) -> None:
        """Детект пропуска (ревью #1): build_monitor отдаёт лишь новейшие `window` строк (закрытое
        recent-N). Курсор прыгнул больше окна → старые строки над курсором выскользнули = возможен
        пропуск телеметрии. ADR-0001-компромисс (всё через build_monitor); полный фикс — курсорный
        direct-read из БД (в QUEUE Куратору). Здесь — хотя бы громко surface'им."""
        if new - prev > window:
            log.warning("%s: курсор прыгнул на %d (>окно build_monitor=%d) — старые записи могли "
                        "выпасть из окна (ВОЗМОЖЕН ПРОПУСК)", label, new - prev, window)

    def _handle_command(self, now: datetime, mono: float) -> bool:
        try:
            resp = self._client.next_command(wait=self._cfg.poll_wait_s)
        except PermanentError as exc:
            log.error("commands/next: перманентный отказ (%s) — пропуск опроса", exc)
            return False
        except TransientError as exc:
            log.warning("commands/next: транзиент (%s) — пропуск, повтор на след. тике", exc)
            return False
        except ValueError as exc:  # малформед 2xx тело (JSONDecodeError) — не роняем тик
            log.warning("commands/next: битый JSON ответа (%s) — пропуск опроса", exc)
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
            # kill-switch латч. Рейзит, если латч НЕ встал (леджер не засеян) → run() поймает;
            # ack/stand НЕ будет, команда останется липкой (повтор, когда леджер засеется).
            self._reader.stop_close()
            # немедленный «stopping» heartbeat — видимость стопа в ядре даже без движка
            uptime = mono - self._start_mono if self._start_mono is not None else 0.0
            self._send(lambda: self._client.heartbeat(
                status="stopping", uptime_s=uptime, contract_version=CONTRACT_VERSION), "heartbeat")
            self._ack(cmd_id, "ok")
            return True  # встаём: цикл завершится, процесс выйдет (restartPolicy=never)
        if cmd == "screener_run":
            # скринер ОТДЕЛЬНЫМ процессом (движок/heartbeat не блокируем, как скаут); он сам
            # пушит статус/результат в ядро по run_id. ack ok = «запущено» (не «досчитано»).
            self._launch_screener(resp.get("payload") or {})
            self._ack(cmd_id, "ok")
            return False
        if cmd == "dozor_apply":
            # Разведка-стол: записать оверрайды дозора (whitelist+coerce) → gen-рестарт скаута
            # супервизором. Ядро=истина; движок не зависит от этого канала.
            self._apply_dozor(resp.get("payload") or {}, cmd_id)
            return False
        if cmd == "scan_now":
            self._scan_now(now, cmd_id)  # кнопка «Сканировать сейчас»
            return False
        # неизвестная команда — ack error (это не stop_close, липкость ядра тут не держит)
        self._ack(cmd_id, "error", {"reason": f"unknown:{cmd}"})
        return False

    def _launch_screener(self, payload: dict) -> None:
        """Запустить app/screener.py отдельным процессом (fire-and-forget). Процесс наследует env
        (MF_CORE_URL/MF_INSTANCE_TOKEN) и сам пушит результат в ядро. RPS=1 (суммарно со скаутом 2 —
        безопасно). Изолированная screener_run.db (не scout.db Галахада)."""
        import os
        import subprocess
        import sys

        run_id = payload.get("run_id")
        p = payload.get("params") or {}
        if not run_id:
            log.warning("screener_run без run_id — пропуск")
            return
        # Ген: скринер = умение у всех, тумблер по умолчанию ВЫКЛ (паттерн SCOUT_ENABLED). Взводим
        # ролью только боту-разведчику (Галахад). Не взведён → сообщаем ядру, консоль не виснет.
        if os.environ.get("SCREENER_ENABLED") != "1":
            log.info("screener_run: SCREENER_ENABLED не взведён — скринер на этом боте выключен")
            self._screener_disabled(run_id)
            return
        args = [
            sys.executable, "-m", "app.screener", "--push", "--run-id", str(run_id), "--rps", "1",
            "--k", str(p.get("k", 1.5)), "--days", str(p.get("days", 14)),
            "--universe-max", str(p.get("universe_max", 150)),
            "--min-age-days", str(p.get("min_age_days", 180)),
            "--min-turnover", str(p.get("min_turnover_usd", 5_000_000)),
        ]
        try:
            subprocess.Popen(args)
            log.info("screener_run запущен отдельным процессом: run_id=%s", run_id)
        except Exception as exc:
            log.error("screener_run не запустился (%s)", exc)

    def _screener_disabled(self, run_id: str) -> None:
        """Скринер выключен (геном: дефолт ВЫКЛ) — отмечаем в ядре error, чтобы консоль не висла."""
        from app.screener import push_results

        try:
            push_results(self._cfg.core_url, self._cfg.instance_token, run_id, "error",
                         summary={"error": "скринер выключен на этом боте (SCREENER_ENABLED=0)"})
        except Exception as exc:
            log.warning("не смог отметить выключенный скринер в ядре (%s)", exc)

    def _apply_dozor(self, payload: dict, cmd_id: str) -> None:
        """dozor_apply: записать оверрайды дозора (whitelist+coerce, страж 2) → супервизор по смене
        gen мягко рестартит ТОЛЬКО скаут. Движок не трогается. Ошибка → ack error (не липкая)."""
        from app.scout_overrides import write_overrides

        try:
            write_overrides(payload.get("settings") or {})
            self._ack(cmd_id, "ok")
        except Exception as exc:  # noqa: BLE001
            log.error("dozor_apply не применён (%s)", exc)
            self._ack(cmd_id, "error", {"reason": str(exc)[:120]})

    def _scan_now(self, now: datetime, cmd_id: str) -> None:
        """scan_now: триггер Этапа B (scan_now_ms в scout_control). Только при живом скауте."""
        if self._scout is None:
            self._ack(cmd_id, "error", {"reason": "scout off"})
            return
        try:
            self._scout.scan_now(now_ms=int(now.timestamp() * 1000))
            self._ack(cmd_id, "ok")
        except Exception as exc:  # noqa: BLE001
            log.error("scan_now не записан (%s)", exc)
            self._ack(cmd_id, "error", {"reason": str(exc)[:120]})

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
