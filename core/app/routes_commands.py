"""Команды боту — шов S4 (←), Контракт v0. Токен принципала `instance`; инстанс берётся из токена.

GET /v1/commands/next — long-poll (как jobs: своя короткая auth-сессия + опрос короткими сессиями
через to_thread, НЕ держит коннект, SCL1). Пусто → {cmd:none, cmd_id:null} (200, по схеме). ack —
обычный короткий запрос. Идемпотентность и переходы статуса — в app/commands.py.
"""

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import authenticate, current_instance
from app.commands import CommandNotFound, ack, deliver_next
from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.models import Instance

router = APIRouter(prefix="/v1")

_POLL_INTERVAL_S = 0.5


def _authenticate_instance(authorization: str | None) -> uuid.UUID:
    """Аутентифицировать принципал `instance` своей короткой сессией (не держим коннект, SCL1)."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "требуется Bearer-токен")
    with get_sessionmaker()() as s:
        tok = authenticate(s, authorization.removeprefix("Bearer "))
        if tok is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен или отозван")
        if tok.principal != "instance":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "не токен инстанса")
        subject = uuid.UUID(tok.subject_id)
        s.commit()  # скользящий TTL
    return subject


def _deliver_and_serialize(instance_id: uuid.UUID) -> dict | None:
    # Синхронный тик доставки (короткая сессия) — гоняется в threadpool (event loop свободен, SCL1).
    sm = get_sessionmaker()
    with sm() as s:
        cmd = deliver_next(s, instance_id, actor=f"instance:{instance_id}")
        payload = {"cmd": cmd.kind, "cmd_id": str(cmd.id)} if cmd is not None else None
        s.commit()
    return payload


@router.get("/commands/next")
async def next_command(
    wait: int = 0,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Следующая команда боту (long-poll). Пусто за окно ?wait= → {cmd:none, cmd_id:null}."""
    instance_id = await asyncio.to_thread(_authenticate_instance, authorization)
    budget = min(max(wait, 0), settings.job_longpoll_max_wait_seconds)
    deadline = time.monotonic() + budget
    while True:
        payload = await asyncio.to_thread(_deliver_and_serialize, instance_id)
        if payload is not None:
            return JSONResponse(payload)
        if time.monotonic() >= deadline:
            return JSONResponse({"cmd": "none", "cmd_id": None})  # канон: cmd=none (schema)
        await asyncio.sleep(_POLL_INTERVAL_S)


class CommandAckIn(BaseModel):
    result: str                  # ok | error
    detail: dict | None = None


@router.post("/commands/{cmd_id}/ack")
def ack_command(
    cmd_id: uuid.UUID,
    body: CommandAckIn,
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> dict:
    """Подтвердить команду. 404 — не команда этого инстанса; 422 — неизвестный result."""
    if body.result not in ("ok", "error"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "result: ok|error")
    try:
        cmd = ack(
            session, cmd_id=cmd_id, instance_id=inst.id, result=body.result,
            detail=body.detail, actor=f"instance:{inst.id}",
        )
    except CommandNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такой команды") from None
    return {"cmd_id": str(cmd.id), "status": cmd.status}
