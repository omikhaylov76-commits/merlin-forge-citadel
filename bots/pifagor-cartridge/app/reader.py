"""PifagorReader — read-only мост к состоянию вендоренного снимка Пифагора (@b75bd17).

ADR-0001: движок НЕ правим. Читаем через ЕГО агрегацию `dashboard.viewmodel.build_monitor` (те же
цифры, что родной дашборд — faithfulness, Куратор #10), подключаясь к БД воркера КАК дашборд:
`DB(owner=False)` — схему не создаём, singleton-lock НЕ берём (владеет только воркер). Команды
транслируем в ОПУБЛИКОВАННЫЕ контролы движка (не в правку кода):
  - pause/resume → `ConfigStore.set("PAUSE_ENABLED", …)` (cycle гейтит вход, держит позиции).
  - stop_close   → `killswitch.apply_state(STOP)` (durable-латч; гасит вход/флэттит под LIVE).

Вендор кладётся на sys.path по `PIFAGOR_HOME` (в образе — /pifagor), дефолт — `bots/pifagor/vendor`
(локальная разработка/тесты). Импорт вендоренных модулей — ЛЕНИВЫЙ (после подмешивания пути).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_vendor_on_path() -> None:
    home = os.environ.get("PIFAGOR_HOME")
    if home:
        vendor = Path(home)
    else:                                                   # дефолт: bots/pifagor/vendor
        vendor = Path(__file__).resolve().parents[2] / "pifagor" / "vendor"
    p = str(vendor)
    if p not in sys.path:
        # APPEND, не insert(0): вендор Пифагора тоже содержит пакет `app` (app/main.py, cycle.py) —
        # коллизия с адаптерным `app`. Аппендом адаптерный `app` (из cwd/rootdir) остаётся первым;
        # уникальные dashboard/storage/state/config/… находятся в вендоре без конфликта.
        sys.path.append(p)


class PifagorReader:
    """БД+сторы Пифагора: телеметрия через build_monitor, команды → контролы движка."""

    def __init__(self, *, database_url: str | None = None, db_path: str | None = None) -> None:
        _ensure_vendor_on_path()
        # Ленивый импорт: вендор уже на пути. Держим модули/классы на инстансе.
        from dashboard.viewmodel import build_monitor
        from risk_capital import killswitch
        from state.capital import CapitalStore
        from state.config import ConfigStore
        from state.store import StateStore
        from storage.db import DB

        self._build_monitor = build_monitor
        self._killswitch = killswitch
        self.db = DB(database_url=database_url, db_path=db_path, owner=False)
        self.config_store = ConfigStore(self.db)
        self.state_store = StateStore(self.db)
        self.capital_store = CapitalStore(self.db)

    # ── телеметрия ────────────────────────────────────────────────────────────

    def snapshot(self, *, now_ms: int | None = None) -> dict:
        """Вью-модель монитора (равна родному дашборду). prices=None → equity fail-soft к снимку
        леджера (dd/kill-switch/state и так на биржевом снимке, от prices не зависят)."""
        return self._build_monitor(
            self.db, capital_store=self.capital_store, config_store=self.config_store,
            state_store=self.state_store, now_ms=now_ms, prices=None,
        )

    def is_paused(self) -> bool:
        return bool(self.config_store.get("PAUSE_ENABLED"))

    # ── контролы (опубликованные механизмы Пифагора, ADR-0001 read-only) ───────

    def pause(self) -> None:
        """ADR-0005 pause: стоп входов, позиции держатся (cycle гейтит eff['PAUSE_ENABLED'])."""
        ok, err = self.config_store.set("PAUSE_ENABLED", True, source="mfc-command")
        if not ok:
            raise RuntimeError(f"pause: config.set отклонён: {err}")

    def resume(self) -> None:
        ok, err = self.config_store.set("PAUSE_ENABLED", False, source="mfc-command")
        if not ok:
            raise RuntimeError(f"resume: config.set отклонён: {err}")

    def warm_now(self, *, now_ms: int) -> None:
        """ГОРН (ADR-0021): интент WARM_AUTO_NOW в config_log воркера (action-канал, config_state
        не трогаем) → движок на след. тике прогоняет авто-warm (auto_eligible). Движок читает
        config_log_latest + in-memory ack (single-shot); id строки = курсор интента."""
        self.db.config_log_append("WARM_AUTO_NOW", None, str(int(now_ms)), source="scan_now")

    def warm_apply(self, coins: list[str]) -> None:
        """F-warm-button (ADR-0022): durable-интент WARM_APPLY в config_log воркера. Движок
        (`maybe_warm`) на след. 15m-тике ставит одобренные монеты — валидный PENDING, вкл.
        reanchored; OPEN/has_active/cap→skip; single-shot по warm-ack. Поле `new` = CSV монет
        (контракт `_parse_warm_approved` вендора). Невалидную монету движок молча skip."""
        csv = ",".join(s.strip().upper() for s in coins if s and s.strip())
        self.db.config_log_append("WARM_APPLY", None, csv, source="button")

    def stop_close(self) -> None:
        """ADR-0005 stop_close: защёлкнуть kill-switch (durable). Движок гасит вход/отменяет
        незалитое, под LIVE_TRADING флэттит позиции; в dry-run — логирует. Латч sticky до clear.
        apply_state → None, если леджер не засеян (mutate=False) — тогда РЕЙЗИМ: цикл не должен
        ack'нуть ok и встать на НЕсработавшем латче (ядро держит липкость → повтор позже)."""
        state = self._killswitch.apply_state(self.capital_store, self._killswitch.STOP)
        if state != self._killswitch.STOP:
            raise RuntimeError("stop_close: kill-switch не защёлкнулся (леджер не засеян)")

    def close(self) -> None:
        closer = getattr(self.db, "close", None)
        if callable(closer):
            closer()
