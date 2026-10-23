"""Задачи клиенту (T-350, 20-03): таблица `tasks`."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_client_tasks"
down_revision: str | None = "0011_underwriter_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("why_text", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_person_inn", sa.String(length=12), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answered_by", sa.Uuid(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=64), nullable=True),
        sa.Column("created_by_actor", sa.String(length=16), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('DOCUMENT', 'EXPLANATION', 'COLLATERAL', 'CONFIRM_REVENUE', "
            "'SIGNATURE', 'GUARANTOR')",
            name=op.f("ck_tasks_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'ANSWERED', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_tasks_status"),
        ),
        sa.CheckConstraint("round >= 1", name=op.f("ck_tasks_round_positive")),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["applications.id"],
            name=op.f("fk_tasks_application_id_applications"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"], ["users.id"], name=op.f("fk_tasks_assignee_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["answered_by"], ["users.id"], name=op.f("fk_tasks_answered_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_application_id"), "tasks", ["application_id"], unique=False)
    op.create_index("ix_tasks_application_round", "tasks", ["application_id", "round"])


def downgrade() -> None:
    op.drop_index("ix_tasks_application_round", table_name="tasks")
    op.drop_index(op.f("ix_tasks_application_id"), table_name="tasks")
    op.drop_table("tasks")
