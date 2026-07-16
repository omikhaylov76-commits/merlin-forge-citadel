"""screener: команда screener_run + прогоны/результаты скринера по параметрам (С7-2б).

Аддитивно: commands += payload (вход команды) и расширение CHECK kind на 'screener_run';
+ screener_runs (прогон: params/status/summary) + screener_findings (строки результата, data JSONB,
каскад с прогоном). Оператор ставит команду → картридж исполняет отдельным процессом → пуш findings.

Revision ID: 0010_screener
Revises: 0009_scout_snapshots
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_screener"
down_revision = "0009_scout_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # commands: вход команды + расширение канона kind на screener_run (аддитивно)
    op.add_column("commands", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint(
        "ck_commands_kind", "commands",
        "kind IN ('pause','resume','stop_close','screener_run')",
    )

    op.create_table(
        "screener_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), nullable=False,
        ),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued','running','done','error')", name="ck_screener_runs_status"
        ),
        comment="Прогоны скринера по параметрам (С7-2б); queued→running→done|error.",
    )
    op.create_index("ix_screener_runs_instance_id", "screener_runs", ["instance_id"])

    op.create_table(
        "screener_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("screener_runs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        comment="Результаты прогона скринера (С7-2б); data — недоверенный JSON.",
    )
    op.create_index("ix_screener_findings_run_id", "screener_findings", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_screener_findings_run_id", table_name="screener_findings")
    op.drop_table("screener_findings")
    op.drop_index("ix_screener_runs_instance_id", table_name="screener_runs")
    op.drop_table("screener_runs")
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint(
        "ck_commands_kind", "commands", "kind IN ('pause','resume','stop_close')",
    )
    op.drop_column("commands", "payload")
