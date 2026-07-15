"""Агрегаты флота для Обзора (#36): боты по статусу, клиенты, AUM, closed-период net+комиссия.

Только ЧТЕНИЕ (суммы существующих полей) — деньги считает ядро, фронт лишь отображает (#32).
Не мутирует состояние → само-ревью ок (#29). Определения агрегатов задокументированы построчно;
бизнес-уточнения (что считать AUM/«к выставлению») — на ратификацию Куратору (QUEUE).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BillingPeriod, Client, EquityPoint, Instance


def fleet_overview(session: Session) -> dict:
    # ── боты по статусу (намерение жизненного цикла) ──────────────────────────────
    status_counts = dict(
        session.execute(select(Instance.status, func.count()).group_by(Instance.status)).all()
    )
    running = int(status_counts.get("running", 0))
    paused = int(status_counts.get("paused", 0))
    total = int(sum(status_counts.values()))

    clients = int(session.execute(select(func.count()).select_from(Client)).scalar_one())

    # ── AUM = сумма ПОСЛЕДНЕЙ equity по каждому инстансу (телеметрия S4, USDT) ─────
    # Дисплей-метрика обзора. Для БИЛЛИНГА equity авторитетно (сверка, MON3) — это НЕ оно.
    latest = (
        select(EquityPoint.instance_id, EquityPoint.equity)
        .distinct(EquityPoint.instance_id)
        .order_by(EquityPoint.instance_id, EquityPoint.ts.desc())
        .subquery()
    )
    aum = session.execute(select(func.coalesce(func.sum(latest.c.equity), 0))).scalar_one()

    # ── closed-периоды: чистый торговый профит + начисленная комиссия (авторитетно, ADR-0011) ──
    pnl_net, commission = session.execute(
        select(
            func.coalesce(func.sum(BillingPeriod.period_net_trading), 0),
            func.coalesce(func.sum(BillingPeriod.commission), 0),
        ).where(BillingPeriod.status == "closed")
    ).one()

    open_periods = int(
        session.execute(
            select(func.count()).select_from(BillingPeriod).where(BillingPeriod.status == "open")
        ).scalar_one()
    )

    return {
        "bots": {"running": running, "paused": paused, "total": total},
        "clients": clients,
        "aum": str(aum),  # деньги — строкой (без float-дрейфа), как везде в API
        "pnl_net_closed": str(pnl_net),
        "commission_accrued": str(commission),
        "open_periods": open_periods,
        "currency": "USDT",
    }
