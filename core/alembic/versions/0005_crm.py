"""CRM-схема Ф3: clients + exchange_accounts + активация отложенных FK у instances

Материализует родителей client_id/account_id (domain-model) и ВКЛЮЧАЕТ отложенные FK у instances
(ADR-0013 «триггер включения»). bot_type_id/profile_id остаются UUID без FK (родители — Ф5).

Бэкофилл: существующие инстансы (демо в облаке, #15) ссылаются на случайные client_id/account_id
без родителей. Перед добавлением FK вставляем плейсхолдеры (is_active=false, name='(backfill Ф3)'),
иначе ADD CONSTRAINT упадёт на сиротах. Порядок: clients → exchange_accounts (FK на clients).
Деньги/биллинг НЕ здесь (fee_pct_default — колонка-заготовка, MON8).

Revision ID: 0005_crm
Revises: 0004_telemetry_commands
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_crm"
down_revision = "0004_telemetry_commands"
branch_labels = None
depends_on = None

_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contacts", sa.Text(), nullable=True),
        sa.Column("contract_ref", sa.Text(), nullable=True),
        # тариф-дефолт долей (0.2=20%), MON8; снапшот в период при закрытии; NULL пока не задан
        sa.Column("fee_pct_default", sa.Numeric(5, 4), nullable=True),
        # user_id — связь с учёткой (портал); UUID без FK до Ф4, чтобы не ломать TRUNCATE users
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "fee_pct_default >= 0 AND fee_pct_default < 1", name="ck_clients_fee_pct_default"
        ),
        comment="Клиент managed-счёта (Ф3, CRM). fee_pct_default — тариф-дефолт (MON8). ADR-0011.",
    )
    op.create_table(
        "exchange_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=_UUID),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        # key_ciphertext — шифр ключей (ADR-0004/0010); СЕКРЕТ, не в лог; NULL пока нет
        sa.Column("key_ciphertext", sa.Text(), nullable=True),
        sa.Column("perms_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "exchange IN ('bybit','okx','bitget')", name="ck_exchange_accounts_exchange"
        ),
        comment="Биржевой счёт клиента (Ф3). key_ciphertext — шифр ключей, не в лог.",
    )
    op.create_index("ix_exchange_accounts_client_id", "exchange_accounts", ["client_id"])

    # Бэкофилл сирот ДО включения FK (иначе ADD CONSTRAINT упадёт). На пустой БД (CI) — no-op.
    op.execute(
        sa.text(
            "INSERT INTO clients (id, name, is_active) "
            "SELECT DISTINCT i.client_id, '(backfill Ф3)', false "
            "FROM instances i LEFT JOIN clients c ON c.id = i.client_id "
            "WHERE c.id IS NULL"
        )
    )
    # account_id → одна строка на счёт (GROUP BY); client_id берём любой из инстансов этого счёта
    op.execute(
        sa.text(
            "INSERT INTO exchange_accounts (id, client_id, exchange, label, is_active) "
            "SELECT i.account_id, (MIN(i.client_id::text))::uuid, 'bybit', '(backfill Ф3)', false "
            "FROM instances i LEFT JOIN exchange_accounts e ON e.id = i.account_id "
            "WHERE e.id IS NULL GROUP BY i.account_id"
        )
    )

    # Включаем отложенные FK (ADR-0013). RESTRICT: клиента/счёт с живым инстансом не удалить.
    op.create_foreign_key(
        "fk_instances_client_id", "instances", "clients", ["client_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_instances_account_id",
        "instances",
        "exchange_accounts",
        ["account_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_instances_account_id", "instances", type_="foreignkey")
    op.drop_constraint("fk_instances_client_id", "instances", type_="foreignkey")
    op.drop_index("ix_exchange_accounts_client_id", table_name="exchange_accounts")
    op.drop_table("exchange_accounts")
    op.drop_table("clients")
