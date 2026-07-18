"""dynamic_settings: критерии динамической вселенной на инстанс (S8 «Динамо-близнец», ADR-0020).

Аддитивно: таблица dynamic_settings (instance_id PK → desired JSONB, ядро=истина). Оператор крутит
в разделе 5 «Динамика» Конструктора → ядро хранит desired-критерии отбора монет из печки
(min_score/stack_max/fresh_bars) → картридж забирает их своим `/self` (boot + периодический re-fetch)
и применяет ЖИВЬЁМ (провайдер читает файл-критерии, БЕЗ рестарта — ADR-0020 D1). Команды НЕ трогаем
(в отличие от дозора: команда `dynamic_apply` не нужна — живое применение через re-fetch). Зеркало
`scout_settings` (0013), но СВОЙ канал: движко-скоуп (что бот БЕРЁТ), дозор-скоуп остаётся на 0018.
Журнал изменений — в audit_log (before/after). Существующее не меняется.

Revision ID: 0014_dynamic_settings
Revises: 0013_scout_settings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_dynamic_settings"
down_revision = "0013_scout_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dynamic_settings",
        sa.Column(
            "instance_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id"), primary_key=True,
        ),
        sa.Column("desired", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        comment="Критерии динамической вселенной на инстанс (S8/ADR-0020); ядро=истина, картридж "
                "забирает своим /self и применяет живьём (min_score/stack_max/fresh_bars).",
    )


def downgrade() -> None:
    op.drop_table("dynamic_settings")
