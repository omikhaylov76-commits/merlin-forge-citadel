"""instances: центральная таблица инстансов (health-свёртка часового, MFC-003)

FK на clients/exchange_accounts/bot_types/profiles ОТЛОЖЕНЫ (ADR-0013): родители появятся со
своими фичами (Ф2/Ф3/Ф5). Здесь — колонки-ссылки (UUID, NOT NULL) без FK-constraint. Это
осознанный YAGNI-шаг в духе 0001 («НЕ весь домен»), а не «молчаливая полудорога».

Revision ID: 0002_instances
Revises: 0001_foundation
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_instances"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        # Ссылки на родителей — FK отложены (ADR-0013), пока это UUID-колонки NOT NULL.
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bot_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("health", sa.String(8), nullable=False, server_default="ok"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("infra_ref", sa.Text(), nullable=True),
        sa.Column("ensemble_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("health IN ('ok','stale','dead')", name="ck_instances_health"),
        sa.CheckConstraint(
            "status IN ('pending','deploying','starting','running','paused',"
            "'stopping','stopped','failed','failed_deploy','stopping_failed')",
            name="ck_instances_status",
        ),
        comment="Инстанс бота: status=намерение, health=свежесть heartbeat. FK — ADR-0013.",
    )
    # ≤1 живой инстанс на счёт (OPS3/MON2): партиал-уникальный индекс по «занятым» статусам —
    # терминальные stopped/failed_deploy освобождают счёт, остальное его занимает.
    op.create_index(
        "uq_instances_one_live_per_account",
        "instances",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('stopped','failed_deploy')"),
    )
    # Скан свежести часовым бьёт по (status, last_heartbeat_at) — вспомогательный индекс.
    op.create_index("ix_instances_status_heartbeat", "instances", ["status", "last_heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_instances_status_heartbeat", table_name="instances")
    op.drop_index("uq_instances_one_live_per_account", table_name="instances")
    op.drop_table("instances")
