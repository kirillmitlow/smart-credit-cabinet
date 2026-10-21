"""Исходная ревизия роли bank_core: схема пустая, таблицы добавляют задачи роли.

Revision ID: bank_core_0001
Revises:
"""

from collections.abc import Sequence

revision: str = "bank_core_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
