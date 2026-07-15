"""exchange_accounts: billing-lifecycle (активация/терминация) для генератора периодов (MFC-F3-3)

billing_activated_at — момент активации биллинга (операторский baseline MON3); генератор ведёт
периоды только для активированных счетов. billing_terminated_at — терминальна: генерация периодов
останавливается (пауза ≠ терминация, #29/#30). Оба nullable. Модель ратифицирована #30/#31.

Revision ID: 0008_billing_lifecycle
Revises: 0007_contract_one_signed
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_billing_lifecycle"
down_revision = "0007_contract_one_signed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exchange_accounts",
        sa.Column("billing_activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exchange_accounts",
        sa.Column("billing_terminated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exchange_accounts", "billing_terminated_at")
    op.drop_column("exchange_accounts", "billing_activated_at")
