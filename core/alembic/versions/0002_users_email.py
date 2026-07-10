"""users.email для логина (шаг 3, auth)

Revision ID: 0002_users_email
Revises: 0001_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_users_email"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default="" — чтобы NOT NULL прошёл при существующих строках; затем дефолт снимаем.
    op.add_column("users", sa.Column("email", sa.String(255), nullable=False, server_default=""))
    op.alter_column("users", "email", server_default=None)
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
