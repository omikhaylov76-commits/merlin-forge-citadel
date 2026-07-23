"""signal_journal: журнал решений ядра-характера (Этап 1 переката 1-to-N, порция №3).

Аддитивно: таблица `signal_journal` (append-only) — товарная запись решений бота для повтора
на клиентском счёте (диспетчер Этапа 2 читает журнал и повторяет; сам журнал торговлю НЕ меняет).
Dedup по (instance_id, seq) — per-core монотонный курсор адаптера, идемпотентный приём (повтор
не дублит). data JSONB — поля события по kind (недоверенный, экранируется на выводе). Ведение-
детали (reanchor/stop_moved/scalp_removed) — вариант C, следующей санкц-дельтой (ADR-0024).

Revision ID: 0016_signal_journal
Revises: 0015_warm_apply_command
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_signal_journal"
down_revision = "0015_warm_apply_command"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_journal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("core", sa.String(length=40), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("setup_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("instance_id", "seq", name="uq_signal_journal_instance_seq"),
        comment="Сигнальный журнал (Этап 1 1-to-N, порция №3); append-only; dedup (instance, seq); "
                "data — недоверенный JSON, экранируется на выводе.",
    )
    op.create_index("ix_signal_journal_instance_id", "signal_journal", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_signal_journal_instance_id", table_name="signal_journal")
    op.drop_table("signal_journal")
