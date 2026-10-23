"""Ручное решение андеррайтера: кто, уровень, код причины, отклонение (T-362, 30-11)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_underwriter_decision"
down_revision: str | None = "0010_bank_user_level"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("decisions", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.add_column("decisions", sa.Column("actor_level", sa.String(length=2), nullable=True))
    op.add_column(
        "decisions", sa.Column("override_reason_code", sa.String(length=32), nullable=True)
    )
    op.add_column("decisions", sa.Column("deviation", sa.Boolean(), nullable=True))
    op.create_foreign_key(
        op.f("fk_decisions_actor_id_users"), "decisions", "users", ["actor_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_decisions_actor_id_users"), "decisions", type_="foreignkey")
    for column in ("deviation", "override_reason_code", "actor_level", "actor_id"):
        op.drop_column("decisions", column)
