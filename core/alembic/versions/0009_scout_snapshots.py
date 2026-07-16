"""scout_snapshots: снимки сетапов скаута (телеметрия S4→, ADR-0016 scout-канал #52).

Replace-семантика per (instance, symbol, tf): ядро upsert'ит присланные пары и УДАЛЯЕТ выпавшие
(сетап умер → строки нет; иначе канбан копит трупы). payload JSONB — весь контрактный снимок
(недоверенный, экранируется на ВЫВОДЕ #53). Телеметрия не аудитится (закон №4 — про действия людей).
uq (instance_id,symbol,tf) — ключ upsert/replace; индекс по instance_id — readout по инстансу.

Revision ID: 0009_scout_snapshots
Revises: 0008_billing_lifecycle
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_scout_snapshots"
down_revision = "0008_billing_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scout_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), nullable=False,
        ),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("tf", sa.String(4), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("scan_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("orders_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", "symbol", "tf", name="uq_scout_instance_symbol_tf"),
        comment=(
            "Снимки сетапов скаута (S4, ADR-0016); replace per (instance,symbol,tf); "
            "payload — недоверенный JSON, экранируется на выводе."
        ),
    )
    op.create_index("ix_scout_snapshots_instance_id", "scout_snapshots", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_scout_snapshots_instance_id", table_name="scout_snapshots")
    op.drop_table("scout_snapshots")
