"""T-332: immutable document originals in Postgres; metadata separate from blobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_documents"
down_revision: str | None = "0012_client_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_blobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("applications.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id")),
        sa.Column(
            "storage_key",
            sa.Uuid(),
            sa.ForeignKey("document_blobs.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("template_version", sa.String(64)),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("parse_status", sa.String(16), nullable=False),
        sa.Column("parsed", postgresql.JSONB()),
        sa.Column("parse_error", sa.String(64)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.CheckConstraint(
            "kind IN ('BANK_STATEMENT_1C','FINANCIALS','CONTRACT',"
            "'CREDIT_AGREEMENT','PAYMENT_SCHEDULE','OTHER')",
            name=op.f("ck_documents_kind"),
        ),
        sa.CheckConstraint(
            "origin IN ('UPLOADED','DEMO_GENERATED','SYSTEM_GENERATED')",
            name=op.f("ck_documents_origin"),
        ),
        sa.CheckConstraint(
            "parse_status IN ('PENDING','PROCESSING','PARSED','FAILED','NOT_REQUIRED')",
            name=op.f("ck_documents_parse_status"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_documents_size_positive")),
    )
    for column in ("company_id", "application_id", "task_id"):
        op.create_index(f"ix_documents_{column}", "documents", [column])
    op.execute("""
        CREATE FUNCTION protect_document_original() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'document_blobs' THEN
            RAISE EXCEPTION 'document originals are immutable';
          END IF;
          IF ROW(NEW.id, NEW.company_id, NEW.application_id, NEW.task_id, NEW.storage_key,
                 NEW.kind, NEW.origin, NEW.template_version, NEW.filename, NEW.mime,
                 NEW.size_bytes, NEW.sha256, NEW.created_by, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.company_id, OLD.application_id, OLD.task_id, OLD.storage_key,
                 OLD.kind, OLD.origin, OLD.template_version, OLD.filename, OLD.mime,
                 OLD.size_bytes, OLD.sha256, OLD.created_by, OLD.created_at) THEN
            RAISE EXCEPTION 'document originals are immutable';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_document_blob BEFORE UPDATE ON document_blobs
          FOR EACH ROW EXECUTE FUNCTION protect_document_original();
        CREATE TRIGGER immutable_document_source BEFORE UPDATE ON documents
          FOR EACH ROW EXECUTE FUNCTION protect_document_original();
    """)


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("document_blobs")
    op.execute("DROP FUNCTION protect_document_original()")
