"""Гвозди на «часового»: dead-man состояния + цикл реально крутит реестр и переживает
падение свёртки. БД не нужна — планировщик в памяти (тесты идут без DATABASE_URL)."""

import asyncio
import time

from app.scheduler import Scheduler


def test_health_stopped_before_start() -> None:
    s = Scheduler(tick_seconds=1)
    h = s.health()
    assert h["state"] == "stopped"
    assert h["tick_age_s"] is None
    assert h["jobs"] == 0


def test_dead_man_detects_stale_tick() -> None:
    # Симулируем заклинивший/умерший цикл: тик застыл дольше порога (dead_after).
    s = Scheduler(tick_seconds=1, dead_after_seconds=0.5)
    s._started = True
    s._last_tick_at = time.monotonic() - 10  # последний оборот — 10с назад
    assert s.health()["state"] == "dead"


def test_loop_ticks_and_runs_registered_job() -> None:
    hits = {"n": 0}
    s = Scheduler(tick_seconds=0.02, dead_after_seconds=0.2)
    s.register("bump", 0.0, lambda: hits.__setitem__("n", hits["n"] + 1))

    async def go() -> dict[str, object]:
        await s.start()
        await asyncio.sleep(0.1)
        snap = s.health()
        await s.stop()
        return snap

    snap = asyncio.run(go())
    assert snap["state"] == "running"
    assert isinstance(snap["tick_age_s"], float) and snap["tick_age_s"] < 0.2
    assert hits["n"] >= 1                      # реестр реально исполнен циклом
    assert s.health()["state"] == "stopped"    # после stop — часовой погашен


def test_failing_job_does_not_kill_loop() -> None:
    hits = {"n": 0}
    s = Scheduler(tick_seconds=0.02, dead_after_seconds=0.5)

    def boom() -> None:
        raise RuntimeError("свёртка рухнула")

    s.register("boom", 0.0, boom)
    s.register("bump", 0.0, lambda: hits.__setitem__("n", hits["n"] + 1))

    async def go() -> None:
        await s.start()
        await asyncio.sleep(0.1)
        await s.stop()

    asyncio.run(go())
    assert hits["n"] >= 1  # сосед упал, а часовой продолжил крутить остальные свёртки


def test_scheduler_survives_second_event_loop() -> None:
    # Регресс на code-review Finding-1: один Scheduler переживает ДВА разных event-loop
    # (общий модульный app + несколько TestClient). Event создаётся в start() (привязка к
    # текущему циклу), иначе _run падает RuntimeError на wait() во втором цикле и часовой тихо
    # умирает. До фикса второй прогон возвращал бы задачу мёртвой (task.done()).
    s = Scheduler(tick_seconds=0.02, dead_after_seconds=0.2)

    async def run_once() -> bool:
        await s.start()
        await asyncio.sleep(0.06)  # дать циклу тикнуть несколько раз
        alive = s._task is not None and not s._task.done()  # цикл жив, не упал на wait()
        await s.stop()
        return alive

    assert asyncio.run(run_once()) is True  # loop #1
    assert asyncio.run(run_once()) is True  # loop #2 — тут был RuntimeError до фикса
