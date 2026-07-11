"""Доставка команд боту — шов S4 (←), Контракт v0 / ADR-0005. Канон: pause · resume · stop_close.

deliver_next: long-poll выдаёт старейшую queued команду инстанса (→ delivered). stop_close «липкий»:
пока instance в stopping — отдаём его stop_close снова, пока бот не ack'нет ok (OPS1). ack двигает
статус инстанса (pause→paused, resume→running; stop_close ok→stopped, error→НЕ гасим, ручное).
Каждая доставка/ack — строка audit_log (закон №4). Идемпотентность по cmd_id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.models import Command, Instance

# Статусы инстанса, из которых доставка stop_close уводит в stopping (живые/пауза/старт).
_STOPPABLE = ("starting", "running", "paused")


class CommandNotFound(Exception):
    """ack по чужой/несуществующей команде (не команда этого инстанса)."""


def _now() -> datetime:
    return datetime.now(UTC)


def deliver_next(session: Session, instance_id: uuid.UUID, *, actor: str) -> Command | None:
    """Выдать следующую команду инстансу. None, если очередь пуста (бот получит cmd=none)."""
    inst = session.get(Instance, instance_id)

    # Липкий stop_close (OPS1): пока инстанс в stopping — повторяем его stop_close без ре-аудита.
    if inst is not None and inst.status == "stopping":
        sticky = session.scalar(
            select(Command)
            .where(
                Command.instance_id == instance_id,
                Command.kind == "stop_close",
                Command.status.in_(("queued", "delivered")),
            )
            .order_by(Command.created_at)
        )
        if sticky is not None:
            if sticky.status == "queued":  # первая выдача — отметим delivered + аудит
                sticky.status = "delivered"
                sticky.delivered_at = _now()
                write_audit(session, actor=actor, action="command_delivered",
                            entity=str(sticky.id), after={"kind": "stop_close"})
            return sticky

    # Обычная доставка: старейшая queued (single-claim через SKIP LOCKED — на случай реплик бота).
    cmd = session.execute(
        select(Command)
        .where(Command.instance_id == instance_id, Command.status == "queued")
        .order_by(Command.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if cmd is None:
        return None

    cmd.status = "delivered"
    cmd.delivered_at = _now()
    if cmd.kind == "stop_close" and inst is not None and inst.status in _STOPPABLE:
        inst.status = "stopping"  # включаем липкость немедленно (OPS1)
    write_audit(session, actor=actor, action="command_delivered", entity=str(cmd.id),
                after={"kind": cmd.kind})
    return cmd


def ack(
    session: Session,
    *,
    cmd_id: uuid.UUID,
    instance_id: uuid.UUID,
    result: str,
    detail: dict | None,
    actor: str,
) -> Command:
    """Завершить команду. result ok|error. Идемпотентно по cmd_id. Двигает статус инстанса."""
    cmd = session.get(Command, cmd_id)
    if cmd is None or cmd.instance_id != instance_id:
        raise CommandNotFound()  # не команда этого инстанса (владение, SEC7)
    if cmd.status in ("acked", "failed"):
        return cmd  # уже завершена — идемпотентный повтор ack

    inst = session.get(Instance, instance_id)
    cmd.result = detail
    cmd.acked_at = _now()
    if result == "ok":
        cmd.status = "acked"
        _apply_ok(cmd, inst)
    else:
        cmd.status = "failed"
        # stop_close error → НЕ гасим (позиции могли не закрыться), инстанс остаётся stopping.
    write_audit(session, actor=actor, action="command_ack", entity=str(cmd.id),
                after={"result": result, "kind": cmd.kind, "status": cmd.status})
    return cmd


def _apply_ok(cmd: Command, inst: Instance | None) -> None:
    if inst is None:
        return
    if cmd.kind == "pause" and inst.status in ("running", "starting"):
        inst.status = "paused"
    elif cmd.kind == "resume" and inst.status == "paused":
        inst.status = "running"
    elif cmd.kind == "stop_close":
        inst.status = "stopped"  # позиции закрыты штатно → инстанс погашен (bot-contract)
