"""FileStore: bytes never appear in metadata/list queries. The caller owns the transaction."""

from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.documents.models import DocumentBlob
from app.shared.errors import not_found
from app.shared.ids import uuid7


class FileStore(Protocol):
    def put(self, content: bytes) -> UUID: ...
    def get(self, key: UUID) -> bytes: ...
    def delete(self, key: UUID) -> None: ...


class PostgresFileStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def put(self, content: bytes) -> UUID:
        key = uuid7()
        self.session.add(DocumentBlob(id=key, content=content, size_bytes=len(content)))
        self.session.flush()
        return key

    def get(self, key: UUID) -> bytes:
        row = self.session.get(DocumentBlob, key)
        if row is None:
            raise not_found("Файл")
        return row.content

    def delete(self, key: UUID) -> None:
        row = self.session.get(DocumentBlob, key)
        if row is not None:
            self.session.delete(row)
