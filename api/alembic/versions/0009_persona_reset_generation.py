"""Поколение демо-компании и ограниченное удаление её журналов при сбросе (T-372)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_persona_reset_generation"
down_revision: str | None = "0008_disbursement_loans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies", sa.Column("demo_generation", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "companies",
        sa.Column("demo_resetting", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_companies_demo_generation"), "companies", "demo_generation >= 0"
    )
    # Исключение только для DELETE, только для ресурсов из транзакционного белого списка.
    # Общие версии policy не разрешается удалять даже при демо-сбросе.
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_journal_change() RETURNS trigger AS $$
        DECLARE
            allowed text[] := string_to_array(current_setting('scc.demo_reset_ids', true), ',');
            outbox_ids text[] := string_to_array(
                current_setting('scc.demo_reset_outbox_ids', true), ',');
        BEGIN
            IF TG_OP = 'DELETE' AND TG_TABLE_NAME <> 'policy_versions' AND EXISTS (
                SELECT 1 FROM jsonb_each_text(to_jsonb(OLD)) AS f
                WHERE f.key IN ('application_id', 'contract_id', 'offer_id', 'decision_id',
                                'company_id', 'object_id')
                  AND f.value = ANY(allowed)
            ) THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'audit_log'
               AND to_jsonb(OLD)->>'object_type' = 'outbox'
               AND to_jsonb(OLD)->>'object_id' = ANY(outbox_ids) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'Журнал % неизменяем', TG_TABLE_NAME USING ERRCODE = 'P0001';
        END;
        $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_journal_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Журнал % неизменяем', TG_TABLE_NAME USING ERRCODE = 'P0001';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.drop_constraint(op.f("ck_companies_demo_generation"), "companies", type_="check")
    op.drop_column("companies", "demo_resetting")
    op.drop_column("companies", "demo_generation")
