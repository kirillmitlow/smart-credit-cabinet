"""Загрузки, парсер выписки 1С, хранение файлов, генерация PDF. Документ: 40-03, 50-12."""

from app.modules.documents import reset as reset  # registers demo cleanup
from app.modules.documents.service import (
    Access,
    UploadContext,
    as_dict,
    company_for,
    get_metadata,
    list_metadata,
    store,
    verified_content,
)
from app.modules.documents.storage import FileStore, PostgresFileStore

__all__ = [
    "Access",
    "FileStore",
    "PostgresFileStore",
    "UploadContext",
    "as_dict",
    "company_for",
    "get_metadata",
    "list_metadata",
    "store",
    "verified_content",
]
