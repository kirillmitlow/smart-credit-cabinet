"""Загрузки, парсер выписки 1С, хранение файлов, генерация PDF. Документ: 40-03, 50-12."""

from app.modules.documents import reset as reset  # registers demo cleanup
from app.modules.documents.pdf import credit_source_hash, render_credit
from app.modules.documents.processing import pending_statements, process_statement, statement_job
from app.modules.documents.service import (
    Access,
    UploadContext,
    as_dict,
    company_for,
    get_metadata,
    list_metadata,
    store,
    store_generated,
    verified_content,
)
from app.modules.documents.statement_parser import (
    ParsedStatement,
    parse_statement,
    validate_statement_set,
)
from app.modules.documents.storage import FileStore, PostgresFileStore

__all__ = [
    "Access",
    "pending_statements",
    "process_statement",
    "statement_job",
    "ParsedStatement",
    "parse_statement",
    "validate_statement_set",
    "FileStore",
    "PostgresFileStore",
    "UploadContext",
    "as_dict",
    "company_for",
    "get_metadata",
    "list_metadata",
    "store",
    "store_generated",
    "render_credit",
    "credit_source_hash",
    "verified_content",
]
