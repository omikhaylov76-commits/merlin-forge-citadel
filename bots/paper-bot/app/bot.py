"""Цикл картриджа: heartbeat ≤60с + tick-телеметрия + опрос/исполнение команд (шов S4).

tick_once — одна итерация (тестируемая): heartbeat при наступлении времени; движок → push
equity/trades/events; опрос команды и ЧЕСТНОЕ исполнение (pause/resume/stop_close). Возвращает
should_stop (True после stop_close → процесс встаёт). run — цикл со сном; best-effort к сбоям сети
(оборот упал → лог + продолжить: бот держится на своих стопах, пока ядро недоступно).

Время разведено: now (стенное) → ts телеметрии; mono (монотонное) → интервалы/uptime. Оба
инъектируются в tick_once — тесты дают фиксированные последовательности.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from app.config import CONTRACT_VERSION, BotConfig
from app.engine import PaperEngine

log = logging.getLogger("mfc.paper-bot")


class PaperBot:
    def __init__(self, client, engine: PaperEngine, config: BotConfig) -> None:
        self._client = client
        self._engine = engine
        self._cfg = config
        self._start_mono: float | None = None
        self._last_hb_mono: float | None = None

    def tick_once(self, now: datetime, mono: float) -> bool:
        """Одна итерация. Возвращает should_stop (True после stop_close)."""
        if self._start_mono is None:
            self._start_mono = mono
        # heartbeat при наступлении времени (≤60с; кормит stale-скан часового)
        hb_due = (
            self._last_hb_mono is None
            or mono - self._last_hb_mono >= self._cfg.heartbeat_interval_s
        )
        if hb_due:
            self._client.heartbeat(
                status=self._engine.heartbeat_status(),
                uptime_s=mono - self._start_mono,
                contract_version=CONTRACT_VERSION,
            )
            self._last_hb_mono = mono
        # телеметрия оборота (в паузе движок шлёт только equity — новых входов нет)
        t = self._engine.tick(now)
        self._client.push_equity(t.equity)
        self._client.push_trades(t.trades)
        self._client.push_events(t.events)
        return self._handle_command(now)

    def _handle_command(self, now: datetime) -> bool:
        resp = self._client.next_command(wait=self._cfg.poll_wait_s)
        cmd, cmd_id = resp.get("cmd"), resp.get("cmd_id")
        if not cmd_id or cmd in (None, "none"):
            return False
        if cmd == "pause":
            self._engine.pause()  # честно: стоп входов, позиции держатся
            self._client.ack_command(cmd_id=cmd_id, result="ok")
            return False
        if cmd == "resume":
            self._engine.resume()
            self._client.ack_command(cmd_id=cmd_id, result="ok")
            return False
        if cmd == "stop_close":
            out = self._engine.stop_close(now)  # честно: закрыть позицию + kill_switch + встать
            self._client.push_trades(out.trades)  # доложить закрывающие сделки/событие/equity
            self._client.push_events(out.events)
            self._client.push_equity(out.equity)
            self._client.ack_command(cmd_id=cmd_id, result="ok")
            return True  # встаём: цикл завершится, процесс выйдет
        # неизвестная команда — ack error (ядро для stop_close держит липкость; тут не stop_close)
        self._client.ack_command(cmd_id=cmd_id, result="error", detail={"reason": f"unknown:{cmd}"})
        return False

    def run(self, stop: threading.Event) -> None:
        """Цикл до stop или stop_close. Сбой оборота (ядро/сеть) — best-effort: лог + продолжить."""
        while not stop.is_set():
            try:
                if self.tick_once(datetime.now(UTC), time.monotonic()):
                    log.info("stop_close исполнен — картридж встаёт")
                    return
            except Exception:  # noqa: BLE001 — ядро/сеть недоступны: не роняем бота (свои стопы держат)
                log.exception("оборот упал — best-effort, продолжаю")
            stop.wait(self._cfg.tick_interval_s)
        log.info("картридж остановлен")
