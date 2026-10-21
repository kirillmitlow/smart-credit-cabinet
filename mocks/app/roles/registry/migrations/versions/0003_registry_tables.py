"""Таблицы mock-registry: организации и ИП, люди, роли, дела ЕФРСБ, справочник ОКВЭД (раздел 4.4).

Revision ID: registry_0003
Revises: registry_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "registry_0003"
down_revision: str | None = "registry_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bankruptcies",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("subject_inn", sa.String(length=12), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("case_number", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("completed_at", sa.Date(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_inn", "case_number"),
    )
    op.create_index(
        op.f("ix_bankruptcies_scenario_code"), "bankruptcies", ["scenario_code"], unique=False
    )
    op.create_index(
        op.f("ix_bankruptcies_subject_inn"), "bankruptcies", ["subject_inn"], unique=False
    )
    op.create_table(
        "okved",
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )
    # Справочник ОКВЭД: коды и названия из примеров спецификации; остальные добавляет запись карточки
    okved = sa.table("okved", sa.column("code", sa.String), sa.column("name", sa.Text))
    op.bulk_insert(
        okved,
        [
            {"code": "25.62", "name": "Обработка металлических изделий механическая"},
            {"code": "28.41", "name": "Производство металлообрабатывающего оборудования"},
            {
                "code": "56.10",
                "name": "Деятельность ресторанов и услуги по доставке продуктов питания",
            },
        ],
    )
    op.create_table(
        "persons",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("owner_inn", sa.String(length=12), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("middle_name", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("inn"),
    )
    op.create_index(op.f("ix_persons_owner_inn"), "persons", ["owner_inn"], unique=False)
    op.create_index(op.f("ix_persons_scenario_code"), "persons", ["scenario_code"], unique=False)
    op.create_table(
        "entities",
        sa.Column("inn", sa.String(length=12), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("ogrn", sa.String(length=15), nullable=False),
        sa.Column("kpp", sa.String(length=9), nullable=True),
        sa.Column("person_inn", sa.String(length=12), nullable=True),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("short_name", sa.Text(), nullable=True),
        sa.Column("okopf_code", sa.String(length=8), nullable=True),
        sa.Column("okopf_name", sa.Text(), nullable=True),
        sa.Column("status_code", sa.String(length=16), nullable=False),
        sa.Column("status_name", sa.Text(), nullable=False),
        sa.Column("status_since", sa.Date(), nullable=False),
        sa.Column("pending_exclusion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("region_code", sa.String(length=2), nullable=False),
        sa.Column("region_name", sa.Text(), nullable=False),
        sa.Column("address_full", sa.Text(), nullable=True),
        sa.Column("address_unreliable", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("authorized_capital_rub", sa.BigInteger(), nullable=True),
        sa.Column("okved_main", sa.String(length=10), nullable=False),
        sa.Column("okved_additional", postgresql.ARRAY(sa.String(length=10)), nullable=False),
        sa.Column("tax_authority_code", sa.String(length=4), nullable=False),
        sa.Column("tax_authority_name", sa.Text(), nullable=False),
        sa.Column("last_record_grn", sa.String(length=15), nullable=False),
        sa.Column("last_record_date", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["person_inn"],
            ["persons.inn"],
        ),
        sa.PrimaryKeyConstraint("inn"),
        sa.UniqueConstraint("ogrn"),
    )
    op.create_index(op.f("ix_entities_scenario_code"), "entities", ["scenario_code"], unique=False)
    op.create_table(
        "entity_roles",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("entity_inn", sa.String(length=12), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("person_inn", sa.String(length=12), nullable=True),
        sa.Column("founder_entity_inn", sa.String(length=10), nullable=True),
        sa.Column("founder_name", sa.Text(), nullable=True),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column("share_percent", sa.Float(), nullable=True),
        sa.Column("share_nominal_rub", sa.BigInteger(), nullable=True),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("unreliable", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("position_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["entity_inn"], ["entities.inn"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["person_inn"],
            ["persons.inn"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_entity_roles_entity_inn"), "entity_roles", ["entity_inn"], unique=False
    )
    op.create_index("ix_entity_roles_person", "entity_roles", ["person_inn"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_entity_roles_person", table_name="entity_roles")
    op.drop_index(op.f("ix_entity_roles_entity_inn"), table_name="entity_roles")
    op.drop_table("entity_roles")
    op.drop_index(op.f("ix_entities_scenario_code"), table_name="entities")
    op.drop_table("entities")
    op.drop_index(op.f("ix_persons_scenario_code"), table_name="persons")
    op.drop_index(op.f("ix_persons_owner_inn"), table_name="persons")
    op.drop_table("persons")
    op.drop_table("okved")
    op.drop_index(op.f("ix_bankruptcies_subject_inn"), table_name="bankruptcies")
    op.drop_index(op.f("ix_bankruptcies_scenario_code"), table_name="bankruptcies")
    op.drop_table("bankruptcies")
