"""Уровень полномочий сотрудников банка (T-213, D-090)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_bank_user_level"
down_revision: str | None = "0009_persona_reset_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("level", sa.String(length=2), nullable=True))
    # До T-213 поле отсутствовало: существующие демо-сотрудники получают уровень D-090.
    op.execute("UPDATE users SET level = 'L2' WHERE role IN ('UNDERWRITER', 'ADMIN')")
    op.create_check_constraint(
        op.f("ck_users_bank_level"),
        "users",
        "(role = 'CLIENT' AND level IS NULL) OR "
        "(role IN ('UNDERWRITER', 'ADMIN') AND level IS NOT NULL "
        "AND level IN ('L1', 'L2'))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_bank_level"), "users", type_="check")
    op.drop_column("users", "level")
