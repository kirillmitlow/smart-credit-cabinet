"""Исходная ревизия роли scenarios: схема пустая, таблицы добавляют задачи роли.

Revision ID: scenarios_0001
Revises:
"""

from collections.abc import Sequence

revision: str = "scenarios_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
