"""PaperEngine — детерминированный фейковый движок картриджа. Без биржи/ключей (paper-only).

equity — синус вокруг базы + вклад открытой позиции (детерминирован по step). «Сделки» — из
seeded-ГПСЧ (random.Random(seed)) → тесты воспроизводимы (разбор #4). Честные семантики ADR-0005:
pause = стоп НОВЫХ входов (позиции ДЕРЖАТСЯ), stop_close = ЗАКРЫТЬ позицию + kill_switch + встать.

Движок ЧИСТЫЙ (без I/O): tick(now) возвращает, ЧТО эмитить; состояние двигают pause/resume/stop.
Цикл (bot.py) пушит это в ядро. ts штампуется из переданного now — тесты дают фиксированный now.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

_SYMBOL = "BTCUSDT"          # paper-инструмент (недоверенное поле — ядро экранирует на выводе)
_BASE_EQUITY = Decimal("10000")
_AMP = Decimal("0.02")       # амплитуда синуса ±2%
_ENTRY_PROB = 0.4            # вероятность события сделки за оборот (только running)


@dataclass
class Tick:
    """Что картридж эмитит за оборот/команду: точка equity + возможные сделки/события."""

    equity: dict
    trades: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


class PaperEngine:
    def __init__(self, seed: int, base_equity: Decimal = _BASE_EQUITY) -> None:
        self._rng = random.Random(seed)
        self._base = base_equity
        self._step = 0
        self._position = Decimal("0")  # чистая открытая позиция (qty)
        self._exec_seq = 0
        self.state = "running"         # running | paused | stopping | stopped
        self._close_tick: Tick | None = None  # результат stop_close — для идемпотентного ретрая

    # ── телеметрия ────────────────────────────────────────────────────────────

    def _equity_value(self) -> Decimal:
        wave = _AMP * Decimal(math.sin(self._step * 0.5))  # детерминированный синус по step
        return (self._base * (Decimal("1") + wave) + self._position * Decimal("100")).quantize(
            Decimal("0.01")
        )

    def _equity_point(self, now: datetime) -> dict:
        return {"ts": now.isoformat(), "equity": float(self._equity_value()), "currency": "USDT"}

    def _make_trade(self, now: datetime) -> dict:
        qty = Decimal(self._rng.randint(1, 5)) / Decimal("100")  # 0.01..0.05
        enter = self._position <= 0 or self._rng.random() < 0.6  # 60% долив, 40% частичное закрытие
        if enter:
            self._position += qty
            side, pnl = "buy", None
        else:
            qty = min(qty, self._position)  # закрываем не больше, чем держим (>0: position>0)
            self._position -= qty
            side = "sell"
            pnl = float(Decimal(self._rng.randint(-50, 100)))  # seeded реализованный PnL
        trade = {
            "ts": now.isoformat(), "exec_id": self._next_exec_id(), "symbol": _SYMBOL,
            "side": side, "qty": float(qty),
        }
        if pnl is not None:
            trade["pnl"] = pnl
        return trade

    def _next_exec_id(self) -> str:
        self._exec_seq += 1
        return f"paper-{self._exec_seq}"  # ключ идемпотентности (dedup ядра по exec_id)

    # ── жизненный цикл ────────────────────────────────────────────────────────

    def tick(self, now: datetime) -> Tick:
        """Оборот. running делает вход/закрытие (seeded); paused — только equity (новых входов НЕТ,
        позиция держится). Возвращает телеметрию к отправке."""
        trades: list[dict] = []
        if self.state == "running" and self._rng.random() < _ENTRY_PROB:
            trades.append(self._make_trade(now))
        point = self._equity_point(now)  # equity включает вклад держимой позиции и в паузе
        self._step += 1
        return Tick(equity=point, trades=trades)

    def pause(self) -> None:
        """ADR-0005 честно: стоп НОВЫХ входов; открытые позиции ДЕРЖАТСЯ (не закрываем)."""
        if self.state == "running":
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self.state = "running"

    def stop_close(self, now: datetime) -> Tick:
        """ADR-0005: ЗАКРЫТЬ позицию (закрывающая сделка) + kill_switch + встать. ИДЕМПОТЕНТНО:
        повторный вызов (ретрай после сбоя пуша до ack) возвращает ТОТ ЖЕ tick — тот же exec_id/ts,
        дедуп ядра безопасен; закрывающий филл и kill_switch не теряются на ретрае (MINOR 2)."""
        if self._close_tick is not None:
            return self._close_tick
        self.state = "stopping"
        events = [
            {"ts": now.isoformat(), "kind": "kill_switch", "detail": {"reason": "stop_close"}}
        ]
        trades: list[dict] = []
        if self._position != 0:
            trades.append({
                "ts": now.isoformat(), "exec_id": self._next_exec_id(), "symbol": _SYMBOL,
                "side": "sell" if self._position > 0 else "buy",
                "qty": float(abs(self._position)), "pnl": 0.0,
            })
            self._position = Decimal("0")
        self.state = "stopped"  # встали: цикл завершится, процесс выйдет
        self._close_tick = Tick(equity=self._equity_point(now), trades=trades, events=events)
        return self._close_tick

    def heartbeat_status(self) -> str:
        """Контракт status: running|paused|stopping|error. stopped → бот выходит, не рапортует."""
        return self.state if self.state in ("running", "paused", "stopping") else "stopping"

    @property
    def position(self) -> Decimal:
        return self._position
