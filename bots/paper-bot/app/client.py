"""CoreClient — клиент API ядра (шов S4, сторона картриджа). Токен инстанса в Bearer.

Тонкая обёртка над ручками MFC-005: push heartbeat/equity/trades/events + long-poll команд + ack.
Ошибки НЕ глотает (raise_for_status) — best-effort решает цикл (bot.py): сеть легла → лог + дальше.
Пустые батчи не шлём. Единственная зависимость — httpx (в тестах подменяется MockTransport).
"""

from __future__ import annotations

import httpx


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

    # ── команды (S4←) ─────────────────────────────────────────────────────────

    def next_command(self, *, wait: int = 25) -> dict:
        """Long-poll команды. Возвращает {cmd, cmd_id} (cmd=none, если за окно пусто)."""
        resp = self._client.get(
            f"{self._base}/v1/commands/next", params={"wait": wait},
            headers=self._h(), timeout=wait + self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def ack_command(self, *, cmd_id: str, result: str, detail: dict | None = None) -> None:
        resp = self._client.post(
            f"{self._base}/v1/commands/{cmd_id}/ack",
            headers=self._h(), json={"result": result, "detail": detail},
        )
        resp.raise_for_status()

    def _post(self, path: str, payload) -> None:
        resp = self._client.post(f"{self._base}{path}", headers=self._h(), json=payload)
        resp.raise_for_status()
