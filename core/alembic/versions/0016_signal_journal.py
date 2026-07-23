"""signal_journal: журнал решений ядра-характера (Этап 1 переката 1-to-N, порция №3).

Аддитивно: таблица `signal_journal` (append-only) — товарная запись решений бота для повтора
на клиентском счёте (диспетчер Этапа 2 читает журнал и повторяет; сам журнал торговлю НЕ меняет).
Dedup по НАТУРАЛЬНОМУ ключу движка (instance_id, src_table, src_id) — id строк worker-БД движка
(signals/fills/events/closed_trades) стабильны и монотонны (MAX(id)+1, не переиспользуются), поэтому
пере-деривация после рестарта адаптера даёт ТЕ ЖЕ ключи → идемпотентно без durable-состояния
(Куратор, вариант A). seq — поле ПОРЯДКА повтора (per-core монотонный), НЕ ключ дедупа. data JSONB —
поля события по kind (недоверенный, экранируется на выводе). Ведение-детали (reanchor/stop_moved/
scalp_removed) — вариант C, следующей санкц-дельтой (ADR-0024).

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
        sa.Column("src_table", sa.String(length=24), nullable=False),  # натуральный ключ движка
        sa.Column("src_id", sa.BigInteger(), nullable=False),          # id строки worker-БД
        sa.Column("seq", sa.BigInteger(), nullable=False),             # порядок повтора (не дедуп)
        sa.Column("core", sa.String(length=40), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("setup_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "instance_id", "src_table", "src_id", name="uq_signal_journal_instance_src",
        ),
        comment="Сигнальный журнал (Этап 1 1-to-N, порция №3); append-only; dedup по натуральному "
                "ключу движка (instance, src_table, src_id); seq — порядок повтора; data — "
                "недоверенный JSON, экранируется на выводе.",
    )
    op.create_index("ix_signal_journal_instance_id", "signal_journal", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_signal_journal_instance_id", table_name="signal_journal")
    op.drop_table("signal_journal")
