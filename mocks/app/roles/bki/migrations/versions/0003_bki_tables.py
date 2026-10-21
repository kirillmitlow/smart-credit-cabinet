"""Таблицы БКИ: субъекты, обязательства, запросы, заявки, банкротства, отчёты, сведения банка.

Revision ID: bki_0003
Revises: bki_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bki_0003"
down_revision: str | None = "bki_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inn"),
    )
    op.create_index(op.f("ix_subjects_scenario_code"), "subjects", ["scenario_code"], unique=False)
    op.create_table(
        "submissions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(op.f("ix_submissions_inn"), "submissions", ["inn"], unique=False)
    op.create_table(
        "applications_info",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("application_ref", sa.String(length=64), nullable=False),
        sa.Column("applied_at", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount_rub", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.Date(), nullable=True),
        sa.Column("is_own", sa.Boolean(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "application_ref", name="uq_application_ref"),
    )
    op.create_index(
        op.f("ix_applications_info_scenario_code"),
        "applications_info",
        ["scenario_code"],
        unique=False,
    )
    op.create_table(
        "bankruptcies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("case_number", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_bankruptcies_scenario_code"), "bankruptcies", ["scenario_code"], unique=False
    )
    op.create_index(
        op.f("ix_bankruptcies_subject_id"), "bankruptcies", ["subject_id"], unique=False
    )
    op.create_table(
        "obligations",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("uid", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("planned_close_at", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.Column("amount_rub", sa.BigInteger(), nullable=True),
        sa.Column("limit_rub", sa.BigInteger(), nullable=True),
        sa.Column("balance_rub", sa.BigInteger(), nullable=False),
        sa.Column("monthly_payment_rub", sa.BigInteger(), nullable=True),
        sa.Column("overdue_rub", sa.BigInteger(), nullable=False),
        sa.Column("overdue_periods", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("secured", sa.Boolean(), nullable=False),
        sa.Column("payment_history_fixed", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    op.create_index(
        op.f("ix_obligations_scenario_code"), "obligations", ["scenario_code"], unique=False
    )
    op.create_index(op.f("ix_obligations_subject_id"), "obligations", ["subject_id"], unique=False)
    op.create_table(
        "reports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("application_ref", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("consent", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reports_inn"), "reports", ["inn"], unique=False)
    op.create_table(
        "inquiries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("inquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_name", sa.String(length=200), nullable=True),
        sa.Column("user_type", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("is_own", sa.Boolean(), nullable=False),
        sa.Column("report_id", sa.String(length=32), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inquiries_inn_inquired_at", "inquiries", ["inn", "inquired_at"], unique=False
    )
    op.create_index(
        op.f("ix_inquiries_scenario_code"), "inquiries", ["scenario_code"], unique=False
    )
    op.create_index(op.f("ix_inquiries_subject_id"), "inquiries", ["subject_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_inquiries_subject_id"), table_name="inquiries")
    op.drop_index(op.f("ix_inquiries_scenario_code"), table_name="inquiries")
    op.drop_index("ix_inquiries_inn_inquired_at", table_name="inquiries")
    op.drop_table("inquiries")
    op.drop_index(op.f("ix_reports_inn"), table_name="reports")
    op.drop_table("reports")
    op.drop_index(op.f("ix_obligations_subject_id"), table_name="obligations")
    op.drop_index(op.f("ix_obligations_scenario_code"), table_name="obligations")
    op.drop_table("obligations")
    op.drop_index(op.f("ix_bankruptcies_subject_id"), table_name="bankruptcies")
    op.drop_index(op.f("ix_bankruptcies_scenario_code"), table_name="bankruptcies")
    op.drop_table("bankruptcies")
    op.drop_index(op.f("ix_applications_info_scenario_code"), table_name="applications_info")
    op.drop_table("applications_info")
    op.drop_index(op.f("ix_submissions_inn"), table_name="submissions")
    op.drop_table("submissions")
    op.drop_index(op.f("ix_subjects_scenario_code"), table_name="subjects")
    op.drop_table("subjects")
