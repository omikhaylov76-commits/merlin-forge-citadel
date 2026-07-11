"""Аудит: запись действия в audit_log (закон №4) + строка лога с request-id для сшивки."""

import logging

from sqlalchemy.orm import Session

from app.models import AuditLog

# request-id попадает в каждую строку автоматически через JsonFormatter (app/logging.py)
_log = logging.getLogger("audit")


def write_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    entity: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    row = AuditLog(actor=actor, action=action, entity=entity, before=before, after=after)
    session.add(row)
    session.flush()  # получить id до коммита
    # сшивка: та же request_id в логе и (по времени/актору) в audit_log
    _log.info("audit action=%s actor=%s audit_id=%s", action, actor, row.id)
    return row
