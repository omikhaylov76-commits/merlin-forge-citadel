"""warm_apply: F-warm-button (ADR-0022) — новая команда Контракта warm_apply.

Аддитивно: расширение CHECK commands.kind на 'warm_apply' — команда «Поставить» валидный сетап по
клику Оператора (Оператор-only, портал НЕ видит; Закон 5). 0-vendor: движок ставит валидный PENDING
(вкл. reanchored) существующим maybe_warm→_warm_one_button; геном не тронут.

Revision ID: 0015_warm_apply_command
Revises: 0014_dynamic_settings
"""

from alembic import op

revision = "0015_warm_apply_command"
down_revision = "0014_dynamic_settings"
branch_labels = None
depends_on = None

_KINDS_OLD = "kind IN ('pause','resume','stop_close','screener_run','dozor_apply','scan_now')"
_KINDS_NEW = ("kind IN ('pause','resume','stop_close','screener_run','dozor_apply','scan_now',"
              "'warm_apply')")


def upgrade() -> None:
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint("ck_commands_kind", "commands", _KINDS_NEW)


def downgrade() -> None:
    op.drop_constraint("ck_commands_kind", "commands", type_="check")
    op.create_check_constraint("ck_commands_kind", "commands", _KINDS_OLD)
