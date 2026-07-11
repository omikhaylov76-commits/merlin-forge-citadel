"""Свёртка часового: stale-скан heartbeat инстансов (MFC-003).

health инстанса производно от свежести last_heartbeat_at (flows:64): ok → stale → dead по
порогам (config). Скан бьёт только по «живым» статусам (running/paused/stopping) с уже
присланным heartbeat (NULL = бот ещё не рапортовал — забота deploy-watch, не наша). Переход
health — строка audit_log (закон №4, actor=system:sentinel). Никаких действий над инстансом
(позиции неизвестны, seams:62): только диагноз; доставка алерта Оператору — с outbox позже.

Свёртка синхронна: часовой гоняет её через asyncio.to_thread, короткая БД-сессия цикл не
блокирует (SCL1). Сессия открывается на прогон и закрывается.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditLog, Instance

# Статусы, где бот обязан слать heartbeat (иначе health не о чем).
_LIVE_STATUSES = ("running", "paused", "stopping")


def classify(age_s: float, stale_after_s: float, dead_after_s: float) -> str:
    """Диагноз по возрасту последнего heartbeat."""
    if age_s > dead_after_s:
        return "dead"
    if age_s > stale_after_s:
        return "stale"
    return "ok"


def scan_once(sm: sessionmaker[Session], stale_after_s: float, dead_after_s: float) -> int:
    """Один проход: пересчитать health по свежести heartbeat. Возвращает число изменений."""
    now = datetime.now(UTC)
    changed = 0
    with sm() as session:
        instances = session.scalars(
            select(Instance).where(
                Instance.status.in_(_LIVE_STATUSES),
                Instance.last_heartbeat_at.is_not(None),
            )
        ).all()
        for inst in instances:
            age = (now - inst.last_heartbeat_at).total_seconds()
            new_health = classify(age, stale_after_s, dead_after_s)
            if new_health == inst.health:
                continue
            # Переход health — в аудит (закон №4). Актор — системный часовой, не человек.
            session.add(
                AuditLog(
                    actor="system:sentinel",
                    action="instance_health",
                    entity=str(inst.id),
                    before={"health": inst.health},
                    after={"health": new_health, "age_s": round(age, 1)},
                )
            )
            inst.health = new_health
            changed += 1
        session.commit()
    return changed
