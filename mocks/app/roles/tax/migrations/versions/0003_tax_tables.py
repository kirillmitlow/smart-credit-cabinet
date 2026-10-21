"""Таблицы mock-tax: субъекты, профиль, отчётность, МСП, НПД, блокировки, госконтракты (5.7).

Revision ID: tax_0003
Revises: tax_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "tax_0003"
down_revision: str | None = "tax_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tax_subjects",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_index(
        op.f("ix_tax_subjects_scenario_code"), "tax_subjects", ["scenario_code"], unique=False
    )
    op.create_table(
        "account_blocks",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("tax_authority_code", sa.String(length=4), nullable=False),
        sa.Column("bik", sa.String(length=9), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("lifted_at", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_blocks_inn"), "account_blocks", ["inn"], unique=False)
    op.create_table(
        "financial_statements",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("form_type", sa.String(length=16), nullable=False),
        sa.Column("submitted_at", sa.Date(), nullable=False),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inn", "year"),
    )
    op.create_table(
        "npd_status",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("registered_at", sa.Date(), nullable=False),
        sa.Column("deregistered_at", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_table(
        "public_contracts",
        sa.Column("registry_number", sa.String(length=19), nullable=False),
        sa.Column("supplier_inn", sa.String(length=12), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.Text(), nullable=False),
        sa.Column("customer_inn", sa.String(length=10), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("price_rub", sa.BigInteger(), nullable=False),
        sa.Column("concluded_at", sa.Date(), nullable=False),
        sa.Column("execution_deadline", sa.Date(), nullable=False),
        sa.Column("payment_deadline", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("paid_rub", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["supplier_inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("registry_number"),
    )
    op.create_index(
        op.f("ix_public_contracts_supplier_inn"), "public_contracts", ["supplier_inn"], unique=False
    )
    op.create_table(
        "sme_registry",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("category", sa.String(length=8), nullable=False),
        sa.Column("included_at", sa.Date(), nullable=False),
        sa.Column("is_newly_created", sa.Boolean(), nullable=False),
        sa.Column("is_social_enterprise", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_table(
        "tax_profiles",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("tax_regimes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("avg_headcount", sa.Integer(), nullable=True),
        sa.Column("headcount_year", sa.Integer(), nullable=True),
        sa.Column("tax_debt_rub", sa.BigInteger(), nullable=False),
        sa.Column("penalties_rub", sa.BigInteger(), nullable=False),
        sa.Column("fines_rub", sa.BigInteger(), nullable=False),
        sa.Column("debts_as_of", sa.Date(), nullable=False),
        sa.Column("income_rub", sa.BigInteger(), nullable=True),
        sa.Column("expenses_rub", sa.BigInteger(), nullable=True),
        sa.Column("income_year", sa.Integer(), nullable=True),
        sa.Column("tax_offenses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_table(
        "taxes_paid",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("total_rub", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["inn"], ["tax_subjects.inn"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("inn", "year"),
    )


def downgrade() -> None:
    op.drop_table("taxes_paid")
    op.drop_table("tax_profiles")
    op.drop_table("sme_registry")
    op.drop_index(op.f("ix_public_contracts_supplier_inn"), table_name="public_contracts")
    op.drop_table("public_contracts")
    op.drop_table("npd_status")
    op.drop_table("financial_statements")
    op.drop_index(op.f("ix_account_blocks_inn"), table_name="account_blocks")
    op.drop_table("account_blocks")
    op.drop_index(op.f("ix_tax_subjects_scenario_code"), table_name="tax_subjects")
    op.drop_table("tax_subjects")
