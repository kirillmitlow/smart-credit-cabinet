"""Таблицы mock-bank-core (раздел 7.7) и счётчики номеров счетов.

Revision ID: bank_core_0003
Revises: bank_core_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bank_core_0003"
down_revision: str | None = "bank_core_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE bank_core_loan_id_seq")
    op.execute("CREATE SEQUENCE bank_core_settlement_serial_seq")
    op.create_table(
        "compliance_lists",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("list_type", sa.String(length=16), nullable=False),
        sa.Column("list_name", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_at", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("inn", "list_type"),
    )
    op.create_index(
        op.f("ix_compliance_lists_scenario_code"),
        "compliance_lists",
        ["scenario_code"],
        unique=False,
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("customer_since", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inn"),
    )
    op.create_index(
        op.f("ix_customers_scenario_code"), "customers", ["scenario_code"], unique=False
    )
    op.create_table(
        "zsk_ratings",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("assessed_at", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_index(
        op.f("ix_zsk_ratings_scenario_code"), "zsk_ratings", ["scenario_code"], unique=False
    )
    op.create_table(
        "accounts",
        sa.Column("number", sa.String(length=20), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.Date(), nullable=False),
        sa.Column("balance_rub", sa.BigInteger(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("number"),
    )
    op.create_index(op.f("ix_accounts_customer_id"), "accounts", ["customer_id"], unique=False)
    op.create_index(op.f("ix_accounts_scenario_code"), "accounts", ["scenario_code"], unique=False)
    op.create_table(
        "monthly_turnover",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("incoming_rub", sa.BigInteger(), nullable=False),
        sa.Column("incoming_net_rub", sa.BigInteger(), nullable=False),
        sa.Column("outgoing_rub", sa.BigInteger(), nullable=False),
        sa.Column("counterparties_in", sa.Integer(), nullable=False),
        sa.Column("counterparties_out", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.PrimaryKeyConstraint("customer_id", "month"),
    )
    op.create_index(
        op.f("ix_monthly_turnover_scenario_code"),
        "monthly_turnover",
        ["scenario_code"],
        unique=False,
    )
    op.create_table(
        "loans",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("application_ref", sa.String(length=64), nullable=False),
        sa.Column("contract_number", sa.String(length=64), nullable=False),
        sa.Column("contract_uid", sa.String(length=64), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount_rub", sa.BigInteger(), nullable=False),
        sa.Column("limit_rub", sa.BigInteger(), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("rate_percent", sa.Float(), nullable=False),
        sa.Column("repayment_type", sa.String(length=16), nullable=False),
        sa.Column("loan_account", sa.String(length=20), nullable=False),
        sa.Column("settlement_account", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("disbursed_at", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["loan_account"],
            ["accounts.number"],
        ),
        sa.ForeignKeyConstraint(
            ["settlement_account"],
            ["accounts.number"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_ref", name="uq_loans_application_ref"),
        sa.UniqueConstraint("contract_number", name="uq_loans_contract_number"),
        sa.UniqueConstraint("contract_uid", name="uq_loans_contract_uid"),
    )
    op.create_index(op.f("ix_loans_customer_id"), "loans", ["customer_id"], unique=False)
    op.create_index(op.f("ix_loans_scenario_code"), "loans", ["scenario_code"], unique=False)
    op.create_table(
        "postings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("debit_account", sa.String(length=20), nullable=False),
        sa.Column("credit_account", sa.String(length=20), nullable=False),
        sa.Column("amount_rub", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("loan_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["loan_id"],
            ["loans.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_postings_credit_account"), "postings", ["credit_account"], unique=False
    )
    op.create_index(op.f("ix_postings_debit_account"), "postings", ["debit_account"], unique=False)
    op.create_index(op.f("ix_postings_loan_id"), "postings", ["loan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_postings_loan_id"), table_name="postings")
    op.drop_index(op.f("ix_postings_debit_account"), table_name="postings")
    op.drop_index(op.f("ix_postings_credit_account"), table_name="postings")
    op.drop_table("postings")
    op.drop_index(op.f("ix_loans_scenario_code"), table_name="loans")
    op.drop_index(op.f("ix_loans_customer_id"), table_name="loans")
    op.drop_table("loans")
    op.drop_index(op.f("ix_monthly_turnover_scenario_code"), table_name="monthly_turnover")
    op.drop_table("monthly_turnover")
    op.drop_index(op.f("ix_accounts_scenario_code"), table_name="accounts")
    op.drop_index(op.f("ix_accounts_customer_id"), table_name="accounts")
    op.drop_table("accounts")
    op.drop_index(op.f("ix_zsk_ratings_scenario_code"), table_name="zsk_ratings")
    op.drop_table("zsk_ratings")
    op.drop_index(op.f("ix_customers_scenario_code"), table_name="customers")
    op.drop_table("customers")
    op.drop_index(op.f("ix_compliance_lists_scenario_code"), table_name="compliance_lists")
    op.drop_table("compliance_lists")
    op.execute("DROP SEQUENCE bank_core_settlement_serial_seq")
    op.execute("DROP SEQUENCE bank_core_loan_id_seq")
