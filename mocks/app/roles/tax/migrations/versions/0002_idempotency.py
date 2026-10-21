"""Таблица ключей идемпотентности (раздел 2.7).

Revision ID: tax_0002
Revises: tax_0001
"""

from collections.abc import Sequence

from app.common.idempotency import create_table_op, drop_table_op

revision: str = "tax_0002"
down_revision: str | None = "tax_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_op()


def downgrade() -> None:
    drop_table_op()
