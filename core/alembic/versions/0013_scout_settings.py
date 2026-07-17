"""scout_settings: настройки дозора на инстанс (Разведка-стол, S7) + новые виды команд.

Аддитивно: таблица scout_settings (instance_id PK → desired JSONB, ядро=истина Q4) + расширение
CHECK commands.kind на 'dozor_apply' и 'scan_now'. Существующее не меняется.
Журнал изменений — в audit_log (before/after).

Revision ID: 0013_scout_settings
Revises: 0012_basket
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_scout_settings"
down_revision = "0012_basket"
branch_labels = None
depends_on = None

_KINDS_OLD = "kind IN ('pause','resume','stop_close','screener_run')"
_KINDS_NEW = "kind IN ('pause','resume','stop_close','screener_run','dozor_apply','scan_now')"


def upgrade() -> None:
    op.create_table(
        "scout_settings",
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), primary_key=True,
        ),
        sa.Column("desired", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        comment="Настройки дозора на инстанс (Разведка-стол, S7); ядро=истина, картридж применяет.",
    )
    # расширяем набор команд: dozor_apply (пороги) + scan_now (кнопка «Сканировать сейчас»)
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint("ck_commands_kind", "commands", _KINDS_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint("ck_commands_kind", "commands", _KINDS_OLD)
    op.drop_table("scout_settings")
