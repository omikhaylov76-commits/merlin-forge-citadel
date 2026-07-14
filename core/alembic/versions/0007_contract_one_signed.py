"""contracts: ≤1 подписанный договор на клиента (адверс-ревью M2)

Партиал-уникальный индекс по client_id для status='signed': два подписанных договора одному клиенту
делали бы снапшот fee_pct в billing_period неоднозначным (деньги). App-слой (routes_crm) проверяет это
до записи и даёт 409; индекс — backstop от гонки. draft/suspended не ограничены.

Revision ID: 0007_contract_one_signed
Revises: 0006_billing
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_contract_one_signed"
down_revision = "0006_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_contracts_one_signed_per_client",
        "contracts",
        ["client_id"],
        unique=True,
        postgresql_where=sa.text("status = 'signed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_contracts_one_signed_per_client", table_name="contracts")
