"""basket_items: Набор Оператора (НАБОР-1, витрина+хранение).

Аддитивно: таблица basket_items — отмеченные сетапы (монета+ТФ+контекст).
Глобальная корзина; НИЧЕГО не торгует (НАБОР-2 — боевой мост — отдельной спекой).
uniq (symbol, tf) — повторная звёздочка upsert'ит контекст. context JSONB недоверен.

Revision ID: 0012_basket
Revises: 0011_engine_state
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_basket"
down_revision = "0011_engine_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "basket_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("tf", sa.String(4), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        # added_by — свободная ссылка на актора (как audit_log.actor), без жёсткого FK на users
        sa.Column("added_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('scout','screener')", name="ck_basket_source"),
        sa.UniqueConstraint("symbol", "tf", name="uq_basket_symbol_tf"),
        comment="Набор Оператора (НАБОР-1, витрина+хранение); uniq монета+ТФ; ничего не торгует; "
                "context — недоверенный JSON, экранируется на выводе.",
    )


def downgrade() -> None:
    op.drop_table("basket_items")
