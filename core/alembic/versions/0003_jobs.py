"""jobs: очередь задач инфры (deploy/teardown) — контракт-таблица шва S3 (ADR-0009)

core — единственный писатель; оркестратор арендует через internal API (long-poll+lease+fencing),
таблицу напрямую НЕ читает (закон №3). instance_id — реальный FK на instances: родитель существует
с 0002 (отложенные FK ADR-0013 касались лишь ещё-не-созданных родителей). Идемпотентность deploy —
партиал-уникальный индекс «≤1 активный deploy на инстанс» (S3). kind='backtest' зарезервирован Ф5:
CHECK его не пускает (заглушка = явная ошибка, seams).

Revision ID: 0003_jobs
Revises: 0002_instances
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_jobs"
down_revision = "0002_instances"
branch_labels = None
depends_on = None

_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_nonce", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('deploy','teardown')", name="ck_jobs_kind"),
        sa.CheckConstraint(
            "status IN ('pending','leased','done','failed')", name="ck_jobs_status"
        ),
        comment="Очередь задач инфры (шов S3, ADR-0009); писатель — только core.",
    )
    # Идемпотентность деплоя (S3): ≤1 активный deploy-job на инстанс. Активные = pending|leased;
    # done/failed освобождают — повторный деплой после провала возможен (с teardown-компенсацией).
    op.create_index(
        "uq_jobs_one_active_deploy_per_instance",
        "jobs",
        ["instance_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'deploy' AND status IN ('pending','leased')"),
    )
    # Аренда берёт старейший pending (FIFO) через SKIP LOCKED — партиал-индекс по created_at.
    op.create_index(
        "ix_jobs_pending",
        "jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_pending", table_name="jobs")
    op.drop_index("uq_jobs_one_active_deploy_per_instance", table_name="jobs")
    op.drop_table("jobs")
