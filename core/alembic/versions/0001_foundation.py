"""foundation: users, api_tokens, audit_log (+ append-only на audit_log)

Revision ID: 0001_foundation
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

# gen_random_uuid() встроен в PG13+ (нам PG16, ADR-0003) — id генерит и БД (raw-insert), и ORM.
_UUID = sa.text("gen_random_uuid()")
_NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID)


def upgrade() -> None:
    op.create_table(
        "users",
        _id(),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint("role IN ('operator','client')", name="ck_users_role"),
        comment="Оператор и клиенты; роль строка+CHECK, не ENUM (расширять легко).",
    )
    op.create_table(
        "api_tokens",
        _id(),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("principal", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "principal IN ('user','instance','orchestrator','ensemble')", name="ck_tokens_principal"
        ),
        comment="Opaque-токены (ADR-0008v2): в БД хэш SHA-256, не токен; отзыв = revoked_at.",
    )
    op.create_index("ix_api_tokens_token_sha256", "api_tokens", ["token_sha256"], unique=True)
    op.create_table(
        "audit_log",
        _id(),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(128), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        comment="Аудит действий (закон №4); append-only на уровне БД (триггер ниже).",
    )
    # Append-only: БД физически запрещает UPDATE/DELETE строк аудита (закон №4 — «без исключений»).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % denied', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only();")
    op.drop_table("audit_log")
    op.drop_index("ix_api_tokens_token_sha256", table_name="api_tokens")
    op.drop_table("api_tokens")
    op.drop_table("users")
