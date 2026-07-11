"""Контекст запроса: request-id для сшивки строк лога с записями audit_log."""

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(rid: str | None = None) -> str:
    rid = rid or uuid.uuid4().hex
    _request_id.set(rid)
    return rid


def get_request_id() -> str:
    return _request_id.get()
