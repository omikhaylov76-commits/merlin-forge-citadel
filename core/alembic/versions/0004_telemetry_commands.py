"""телеметрия + команды: equity_points/trades/events/commands — приёмная сторона Контракта (шов S4)

core — единственный писатель; бот шлёт через API токеном инстанса (закон №3). Все FK на instances
(родитель есть с 0002). Телеметрия идемпотентна dedup-констрейнтами (bot-contract): equity (inst,
ts), trades (inst, exec_id биржи — не по ts, со-секундные COH4), events (inst, ts, kind).
received_at — серверное время (авторитетно). Индексы (instance, ts DESC) — под выборку хвоста серии.
commands — очередь команд боту (ADR-0005), доставка long-poll; cmd_id = id.

Revision ID: 0004_telemetry_commands
Revises: 0003_jobs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_telemetry_commands"
down_revision = "0003_jobs"
branch_labels = None
depends_on = None

_UUID = sa.text("gen_random_uuid()")


def _telemetry_base() -> list:
    # Общие колонки телеметрии: id + FK на инстанс + ts бота + received_at сервера.
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "equity_points",
        *_telemetry_base(),
        sa.Column("equity", sa.Numeric(), nullable=False),  # деньги — Numeric, не float
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("working", sa.Numeric(), nullable=True),
        sa.Column("cushion", sa.Numeric(), nullable=True),
        sa.UniqueConstraint("instance_id", "ts", name="uq_equity_instance_ts"),
        comment="Кривая equity бота (S4); received_at авторитетно; dedup (instance, ts).",
    )
    op.create_index("ix_equity_instance_ts", "equity_points", ["instance_id", sa.text("ts DESC")])

    op.create_table(
        "trades",
        *_telemetry_base(),
        sa.Column("exec_id", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("pnl", sa.Numeric(), nullable=True),
        sa.UniqueConstraint("instance_id", "exec_id", name="uq_trades_instance_exec"),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_trades_side"),
        comment="Сделки бота (S4); dedup по (instance, exec_id биржи), идемпотентно (COH4).",
    )
    op.create_index("ix_trades_instance_ts", "trades", ["instance_id", sa.text("ts DESC")])

    op.create_table(
        "events",
        *_telemetry_base(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("instance_id", "ts", "kind", name="uq_events_instance_ts_kind"),
        comment="События бота (S4); dedup (instance, ts, kind); detail — недоверенный JSON.",
    )
    op.create_index("ix_events_instance_ts", "events", ["instance_id", sa.text("ts DESC")])

    op.create_table(
        "commands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('pause','resume','stop_close')", name="ck_commands_kind"),
        sa.CheckConstraint(
            "status IN ('queued','delivered','acked','failed')", name="ck_commands_status"
        ),
        comment="Очередь команд боту (S4←, ADR-0005); канон pause/resume/stop_close.",
    )
    # Доставка long-poll берёт активные (queued|delivered) по инстансу FIFO; ack'нутые вне выборки.
    op.create_index(
        "ix_commands_active", "commands", ["instance_id", "created_at"],
        postgresql_where=sa.text("status IN ('queued','delivered')"),
    )


def downgrade() -> None:
    op.drop_index("ix_commands_active", table_name="commands")
    op.drop_table("commands")
    op.drop_index("ix_events_instance_ts", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_trades_instance_ts", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_equity_instance_ts", table_name="equity_points")
    op.drop_table("equity_points")
