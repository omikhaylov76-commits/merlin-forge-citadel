"""billing Ф3: contracts + billing_periods + cashflows (модель HWM, ADR-0011 финализирована)

Типизированные колонки (ядро владеет биллингом, НЕ jsonb; #23). billing_periods — период-леджер
на счёт+клиент+инстанс во времени (#23-доп); закрытый период immutable (триггер).
Логику движка НЕ содержит (billing.py); здесь только схема. Деньги: ревью перед merge.

Revision ID: 0006_billing
Revises: 0005_crm
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_billing"
down_revision = "0005_crm"
branch_labels = None
depends_on = None

_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "client_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("payment_model", sa.String(16), nullable=False, server_default="profit_hwm"),
        sa.Column("fee_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.15")),
        sa.Column("high_water_mark", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mgmt_fee_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("hurdle_pct", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("billing_period", sa.String(8), nullable=False, server_default="month"),
        sa.Column("capital", sa.Numeric(18, 2), nullable=False, server_default=sa.text("1000")),
        sa.Column(
            "withdrawal_notice_days", sa.Integer(), nullable=False, server_default=sa.text("3")
        ),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "payment_model IN ('profit_hwm','capital_fixed','hybrid','subscription')",
            name="ck_contracts_payment_model",
        ),
        sa.CheckConstraint("fee_pct >= 0 AND fee_pct < 1", name="ck_contracts_fee_pct"),
        sa.CheckConstraint("mgmt_fee_pct >= 0", name="ck_contracts_mgmt_fee_pct"),
        sa.CheckConstraint("hurdle_pct >= 0", name="ck_contracts_hurdle_pct"),
        sa.CheckConstraint("billing_period IN ('month','quarter')", name="ck_contracts_bperiod"),
        sa.CheckConstraint("capital >= 500", name="ck_contracts_capital_floor"),
        sa.CheckConstraint("currency IN ('USDT','USDC')", name="ck_contracts_currency"),
        sa.CheckConstraint("status IN ('draft','signed','suspended')", name="ck_contracts_status"),
        comment="Договор клиента (Ф3): условия биллинга; fee_pct снапшот (ADR-0011).",
    )
    op.create_index("ix_contracts_client_id", "contracts", ["client_id"])

    op.create_table(
        "billing_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "account_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exchange_accounts.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "client_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "contract_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False,
        ),
        # instance_id — активный бот в периоде (роллап #23-доп); UUID без FK (бот сносится)
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_equity", sa.Numeric(18, 2), nullable=False),
        sa.Column("end_equity", sa.Numeric(18, 2), nullable=True),
        sa.Column("net_deposits", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("period_net_trading", sa.Numeric(18, 2), nullable=True),
        sa.Column("cum_profit", sa.Numeric(18, 2), nullable=True),
        sa.Column("hwm", sa.Numeric(18, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("fee_pct", sa.Numeric(5, 4), nullable=True),  # снапшот при закрытии
        sa.Column("commission", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USDT"),
        sa.Column("status", sa.String(8), nullable=False, server_default="open"),
        sa.Column("adjustments_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_billing_periods_status"),
        comment="Период биллинга: счёт+клиент+инстанс во времени (#23-доп); закрытый immutable.",
    )
    op.create_index("ix_billing_periods_account_id", "billing_periods", ["account_id"])
    op.create_index("ix_billing_periods_client_id", "billing_periods", ["client_id"])
    # Immutability закрытого периода: БД запрещает UPDATE/DELETE строк со status='closed' (деньги).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION billing_period_closed_immutable() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'closed' THEN
                RAISE EXCEPTION 'billing_period % closed, immutable: % denied', OLD.id, TG_OP;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billing_period_closed_immutable
        BEFORE UPDATE OR DELETE ON billing_periods
        FOR EACH ROW EXECUTE FUNCTION billing_period_closed_immutable();
        """
    )

    op.create_table(
        "cashflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "account_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exchange_accounts.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('deposit','withdrawal')", name="ck_cashflows_kind"),
        sa.CheckConstraint("amount > 0", name="ck_cashflows_amount_positive"),
        comment="Пополнения/выводы клиента (ADR-0011); не прибыль/убыток, сдвигают HWM (#24).",
    )
    op.create_index("ix_cashflows_account_id", "cashflows", ["account_id"])


def downgrade() -> None:
    op.drop_table("cashflows")
    op.execute("DROP TRIGGER IF EXISTS trg_billing_period_closed_immutable ON billing_periods;")
    op.execute("DROP FUNCTION IF EXISTS billing_period_closed_immutable();")
    op.drop_table("billing_periods")
    op.drop_table("contracts")
