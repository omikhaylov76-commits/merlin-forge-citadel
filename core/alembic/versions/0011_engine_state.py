"""engine_states: последнее движковое состояние инстанса (карточка бота, S7).

Аддитивно: таблица `engine_states` (instance_id PK → один ряд на инстанс, replace-upsert).
payload JSONB — компакт факт-слоя (статус/капитал/позиции/ордера/хвосты сделок-событий),
недоверенный, экранируется на выводе. Картридж пушит каденцией телеметрии; консоль читает readout.

Revision ID: 0011_engine_state
Revises: 0010_screener
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_engine_state"
down_revision = "0010_screener"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "engine_states",
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), primary_key=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment="Last engine_state per instance (карточка бота, S7); JSONB, replace-upsert.",
    )


def downgrade() -> None:
    op.drop_table("engine_states")
