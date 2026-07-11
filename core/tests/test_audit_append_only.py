"""Гвоздь на закон №4: audit_log append-only — БД физически отвергает UPDATE и DELETE."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog


def test_insert_ok(session):
    row = AuditLog(actor="operator:test", action="login")
    session.add(row)
    session.commit()
    assert row.id is not None  # вставка работает


def test_update_denied(session):
    row = AuditLog(actor="operator:test", action="login")
    session.add(row)
    session.commit()
    with pytest.raises(DBAPIError):  # триггер поднимает исключение → SQLAlchemy оборачивает
        session.execute(text("UPDATE audit_log SET action='tamper' WHERE id=:i"), {"i": row.id})
        session.commit()
    session.rollback()


def test_delete_denied(session):
    row = AuditLog(actor="operator:test", action="login")
    session.add(row)
    session.commit()
    with pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM audit_log WHERE id=:i"), {"i": row.id})
        session.commit()
    session.rollback()
