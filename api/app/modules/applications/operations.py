"""Публичный контекст операции над заявкой: аренда компании живёт и во время сети."""

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from app.modules import companies
from app.modules.applications.models import Application
from app.shared import db, operations


def scope(application_id: UUID) -> operations.Scope | None:
    with db.transaction() as session:
        application = session.get(Application, application_id)
        company_id = application.company_id if application is not None else None
    return companies.operation_scope(company_id) if company_id is not None else None


@contextmanager
def hold(application_id: UUID) -> Iterator[operations.Scope | None]:
    with operations.hold(lambda: scope(application_id)) as current:
        yield current
