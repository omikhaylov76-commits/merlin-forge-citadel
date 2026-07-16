"""CoreClient — клиент API ядра (шов S4, сторона картриджа Пифагора). Токен инстанса в Bearer.

Отличие от эталона `bots/paper-bot` (где цикл ретраит ЛЮБОЙ сбой одинаково best-effort): здесь
**классификация ошибок ОБЯЗАТЕЛЬНА** (Куратор #6/#7, гейт Ф2). Реальная обёртка боевого движка не
имеет права бесконечно долбить ядро перманентными 4xx (401 отозванный токен, 422 битый payload):

  - **транзиентное** (сеть/timeout, 408/425/429, 5xx) → ретрай с экспоненциальным backoff.
  - **перманентное** (400/401/403/404/409/422 …) → НЕ ретраим: PermanentError, цикл логирует и
    идёт дальше (не долбит). 401/403 — токен мёртв (закон №2: тело/токен в лог не льём).
  - **413 (payload too large)** → PayloadTooLarge: цикл дробит батч (Контракт: «413 → бот дробит»).

Единственная зависимость — httpx (в тестах подменяется MockTransport). Секреты в лог НЕ попадают:
причина ошибки = статус + путь, без эха тела/заголовков.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable

import httpx


class CoreError(Exception):
    """База ошибок обращения к ядру. status=None для сетевых сбоев (ответа не было)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TransientError(CoreError):
    """Временный сбой — можно ретраить с backoff (сеть/timeout, 408/425/429, 5xx)."""


class PermanentError(CoreError):
    """Постоянный сбой — ретрай бессмыслен (400/401/403/404/409/422 …). Логируем и идём дальше."""


class PayloadTooLarge(CoreError):
    """413 — батч велик: дробить и слать частями (Контракт)."""


# Транзиентные 4xx: таймаут запроса, «слишком рано», rate-limit. Остальные 4xx — перманентные.
_TRANSIENT_4XX = frozenset({408, 425, 429})


def classify_status(status: int) -> str:
    """Чистая классификация HTTP-статуса: 'ok' | 'transient' | 'permanent' | 'too_large'.
    Единый источник правды 4xx/5xx — тестируется отдельно (гейт #6/#7)."""
    if 200 <= status < 300:
        return "ok"
    if status == 413:
        return "too_large"
    if status in _TRANSIENT_4XX:
        return "transient"
    if 400 <= status < 500:
        return "permanent"
    if status >= 500:
        return "transient"
    return "permanent"  # неожиданный (1xx/3xx на не-редиректном клиенте) — не ретраим вслепую


def _raise_for(status: int, path: str) -> None:
    """Поднять типизированную ошибку по статусу (без эха тела — закон №2)."""
    kind = classify_status(status)
    if kind == "ok":
        return
    msg = f"{status} на {path}"
    if kind == "too_large":
        raise PayloadTooLarge(msg, status=status)
    if kind == "transient":
        raise TransientError(msg, status=status)
    raise PermanentError(msg, status=status)


class CoreClient:
    def __init__(
        self, *, base_url: str, token: str,
        client: httpx.Client | None = None, timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    # ── телеметрия (S4→) ──────────────────────────────────────────────────────

    def heartbeat(self, *, status: str, uptime_s: float, contract_version: str) -> None:
        self._post("/v1/telemetry/heartbeat", {
            "status": status, "uptime_s": uptime_s, "contract_version": contract_version,
        })

    def push_equity(self, point: dict) -> None:
        self._post("/v1/telemetry/equity", point)

    def push_trades(self, trades: list[dict]) -> None:
        if trades:
            self._post("/v1/telemetry/trades", trades)

    def push_events(self, events: list[dict]) -> None:
        if events:
            self._post("/v1/telemetry/events", events)

    def push_scout(self, snapshots: list[dict]) -> None:
        # Шлём ВСЕГДА (в т.ч. []): пустой набор = сетапы исчезли → ядро очистит (replace).
        self._post("/v1/telemetry/scout", snapshots)

    # ── команды (S4←) ─────────────────────────────────────────────────────────

    def next_command(self, *, wait: int = 25) -> dict:
        """Long-poll команды. Возвращает {cmd, cmd_id} (cmd=none, если за окно пусто)."""
        return self._request(
            "GET", "/v1/commands/next", params={"wait": wait}, timeout=wait + self._timeout,
        ).json()

    def ack_command(self, *, cmd_id: str, result: str, detail: dict | None = None) -> None:
        self._request(
            "POST", f"/v1/commands/{cmd_id}/ack", json={"result": result, "detail": detail},
        )

    # ── транспорт ─────────────────────────────────────────────────────────────

    def _post(self, path: str, payload) -> None:
        self._request("POST", path, json=payload)

    def _request(
        self, method: str, path: str, *, json=None, params=None, timeout=None,
    ) -> httpx.Response:
        try:
            resp = self._client.request(
                method, f"{self._base}{path}", headers=self._h(),
                json=json, params=params, timeout=timeout or self._timeout,
            )
        except httpx.TransportError as exc:                 # сеть/timeout — ответа нет → транзиент
            raise TransientError(f"сеть на {path}: {type(exc).__name__}") from exc
        _raise_for(resp.status_code, path)
        return resp


def send_with_backoff(
    fn: Callable[[], None], *, retries: int, base_s: float, cap_s: float,
    sleep: Callable[[float], None] = _time.sleep,
) -> None:
    """Выполнить fn() с ретраем ТОЛЬКО транзиентных ошибок (экспоненциальный backoff, cap).
    PermanentError/PayloadTooLarge пробрасываются СРАЗУ (ретрай бессмыслен/нужно дробить).
    Исчерпав `retries` транзиентных попыток — пробрасываем последний TransientError (цикл логирует).

    sleep инъектируется (тесты дают no-op → без реальных пауз)."""
    for attempt in range(retries + 1):
        try:
            fn()
            return
        except TransientError:
            if attempt >= retries:
                raise
            sleep(min(cap_s, base_s * (2 ** attempt)))
