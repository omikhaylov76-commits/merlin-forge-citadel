"""«Часовой» ядра: один asyncio-цикл + реестр свёрток (периодических задач).

Зачем отдельный модуль: цикл живёт ВНУТРИ процесса ядра (без нового шва наружу), но его
жизнь надо доказывать. Каждый оборот цикла штампует монотонное время — «dead-man тик»
(SCL3, seams.md): /healthz показывает свежесть штампа, и если цикл умер при живом процессе,
это видно. Порог «мёртв» = 3× периода тика (паттерн 3×60с из seams.md:62).

Реестр свёрток — плагин-точка: свёртка = имя + период + функция (обычная `def` ИЛИ `async
def`; объект с async `__call__` не поддержан). В MFC-002 реестр поедет пустым (первая
настоящая свёртка — stale-скан heartbeat — ждёт схему инстансов). Механизм доказан тестом:
цикл вызывает зарегистрированную функцию и изолирует её падение — сосед не роняет часового.

Монотонные часы (time.monotonic), а не стенные: dead-man не должен врать при сдвиге NTP.
Event `_stop` создаётся в start() (в запущенном loop), а НЕ в __init__: иначе он привяжется к
первому же циклу и переиспользование Scheduler между event-loop'ами (общий app + N TestClient)
уронит _run на wait(). Потокобезопасность health(): поля читаются из threadpool-потока ручки и
опираются на GIL (атомарный LOAD_ATTR); на free-threaded build (3.13+ nogil) понадобится замок.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

log = logging.getLogger("mfc.scheduler")

# Свёртка — обычная sync-функция (её гоним в пуле, чтобы блокирующий IO не стопорил цикл)
# ЛИБО async def (её awaitim). См. _run_due_jobs. Объект с async __call__ не поддержан.
JobFn = Callable[[], None] | Callable[[], Awaitable[None]]


@dataclass
class Job:
    """Свёртка: периодическая задача часового."""

    name: str
    interval_s: float                                   # как часто запускать
    fn: JobFn
    _last_run: float = field(default=0.0, repr=False)   # монотонное время прошлого запуска


class Scheduler:
    """Один asyncio-цикл. Оборот = выполнить дозревшие свёртки, затем штамп тика (dead-man)."""

    def __init__(self, tick_seconds: float = 60.0, dead_after_seconds: float | None = None) -> None:
        self._tick_s = tick_seconds
        # «мёртв», если тик не обновлялся дольше 3× периода (паттерн 3×60с, seams.md:62).
        # Порог должен превышать worst-case длительность самой долгой свёртки: тик штампуется
        # ПОСЛЕ свёрток, поэтому живой, но занятый долгой задачей цикл иначе мигнёт в dead.
        self._dead_after_s = (
            dead_after_seconds if dead_after_seconds is not None else tick_seconds * 3
        )
        self._jobs: list[Job] = []
        self._last_tick_at: float | None = None
        self._started = False
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None  # создаётся в start() (привязка к живому loop)

    def register(self, name: str, interval_s: float, fn: JobFn) -> None:
        """Добавить свёртку в реестр. Только ДО старта цикла (реестр не рассчитан на гонку
        с итерацией в _run_due_jobs)."""
        self._jobs.append(Job(name=name, interval_s=interval_s, fn=fn))

    async def start(self) -> None:
        """Запустить цикл. Идемпотентно: повторный старт не плодит вторую задачу/Event."""
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()           # в текущем loop → привязка к нему, не к чужому
        self._last_tick_at = time.monotonic()  # dead-man взведён немедленно (до флага _started)
        self._started = True
        self._task = asyncio.create_task(self._run(), name="mfc-scheduler")
        log.info("часовой запущен: период=%.3fs, свёрток=%d", self._tick_s, len(self._jobs))

    async def stop(self) -> None:
        """Мягко погасить цикл: сигнал + отмена + дождаться. Безопасно и без старта."""
        if self._task is None:
            self._started = False
            return
        assert self._stop is not None  # _task есть ⇒ start() создал _stop
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception:  # цикл уже мог упасть сам — не роняем остановку
            log.exception("часовой завершился с ошибкой")
        self._task = None      # разрешаем повторный start() (напр. рестарт супервизором)
        self._started = False
        log.info("часовой остановлен")

    async def _run(self) -> None:
        assert self._stop is not None  # _run стартует только из start(), где _stop уже создан
        while not self._stop.is_set():
            try:
                await self._run_due_jobs()
                self._last_tick_at = time.monotonic()  # тик = оборот завершён (dead-man)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Непредвиденная ошибка оборота: цикл прекращает тикать — dead-man в /healthz
                # это покажет. Наружу задачу не роняем (иначе «task exception never retrieved»).
                log.exception("часовой: непредвиденная ошибка в обороте цикла")
                return
            try:
                # Спим период, но просыпаемся мгновенно на stop.
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_s)
            except TimeoutError:
                pass  # период истёк — следующий оборот

    async def _run_due_jobs(self) -> None:
        now = time.monotonic()
        for job in self._jobs:
            if now - job._last_run < job.interval_s:
                continue
            job._last_run = now  # до await: упавшая/долгая свёртка не устраивает retry-шторм
            try:
                if asyncio.iscoroutinefunction(job.fn):
                    await job.fn()
                else:
                    # sync-свёртка в пул: не блокируем цикл. Задача в пуле НЕ отменяется на
                    # stop() — свёртки обязаны быть короткими/кооперативными.
                    await asyncio.to_thread(job.fn)
            except Exception:  # падение свёртки не роняет часового (изоляция отказа соседа)
                log.exception("свёртка '%s' упала", job.name)

    def health(self) -> dict[str, object]:
        """Снимок для /healthz: state stopped|running|dead + возраст тика + число свёрток."""
        if not self._started or self._last_tick_at is None:
            return {"state": "stopped", "tick_age_s": None, "jobs": len(self._jobs)}
        age = time.monotonic() - self._last_tick_at
        state = "dead" if age > self._dead_after_s else "running"  # вариант A: /healthz не гейт
        return {"state": state, "tick_age_s": round(age, 3), "jobs": len(self._jobs)}
