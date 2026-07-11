"""CoreClient — клиент internal API ядра (шов S3). Оркестратор таблицу jobs НЕ читает (закон №3).

Две ручки ADR-0009: арендовать (GET /internal/jobs/next?wait=) и завершить (POST …/ack). 204 →
None (за окно ничего не досталось). Транспорт — httpx (в тестах подменяется MockTransport). Токен —
принципал orchestrator (ADR-0008). Ошибку сети/ядра НЕ глотаем — пусть решает worker (backoff).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Lease:
    """Арендованный job: что делать (kind/payload) + fencing-nonce для ack (OPS2)."""

    id: str
    kind: str
    instance_id: str
    payload: dict
    lease_nonce: str


class CoreClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def lease_next(self, *, wait: int = 25) -> Lease | None:
        """Арендовать следующий job (long-poll). None, если за окно ?wait= пусто (204)."""
        resp = self._client.get(
            f"{self._base}/v1/internal/jobs/next",
            params={"wait": wait},
            headers=self._headers(),
            timeout=wait + self._timeout,  # запас поверх серверного окна ожидания
        )
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        d = resp.json()
        return Lease(
            id=d["id"],
            kind=d["kind"],
            instance_id=d["instance_id"],
            payload=d.get("payload") or {},
            lease_nonce=d["lease_nonce"],
        )

    def ack(
        self,
        *,
        job_id: str,
        lease_nonce: str,
        result: str,
        detail: dict | None = None,
        terminal: bool = False,
    ) -> None:
        """Завершить попытку по job. result: done | failed | release (fencing по lease_nonce)."""
        resp = self._client.post(
            f"{self._base}/v1/internal/jobs/{job_id}/ack",
            headers=self._headers(),
            json={
                "lease_nonce": lease_nonce,
                "result": result,
                "detail": detail,
                "terminal": terminal,
            },
        )
        resp.raise_for_status()
