"""Сценарии и журнал их применения (10.7).

Revision ID: scenarios_0003
Revises: scenarios_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "scenarios_0003"
down_revision: str | None = "scenarios_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("builtin_version", sa.Integer()),
        sa.Column("modified", sa.Boolean(), nullable=False),
        sa.Column("expected_outcome", sa.String(32)),
        sa.Column("expected_final_outcome", sa.String(32)),
        sa.Column("expected_reason_codes", JSONB(), nullable=False),
        sa.Column("inn", sa.String(12), unique=True),
        sa.Column("spec", JSONB(), nullable=False),
        sa.Column("expanded", JSONB()),
        sa.Column("applied", JSONB()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("needs_reapply", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("applied_month", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("origin IN ('BUILTIN', 'CUSTOM')", name="ck_scenarios_origin"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPLIED', 'PARTIAL', 'FAILED')", name="ck_scenarios_status"
        ),
    )
    op.create_table(
        "scenario_applications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "scenario_code",
            sa.String(64),
            sa.ForeignKey("scenarios.code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("system", sa.String(16), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "system IN ('REGISTRY', 'TAX', 'BKI', 'BANK_CORE')", name="ck_applications_system"
        ),
        sa.CheckConstraint("action IN ('PUT', 'DELETE')", name="ck_applications_action"),
    )
    op.create_index(
        "ix_scenario_applications_scenario_code", "scenario_applications", ["scenario_code"]
    )


def downgrade() -> None:
    op.drop_index("ix_scenario_applications_scenario_code", table_name="scenario_applications")
    op.drop_table("scenario_applications")
    op.drop_table("scenarios")
