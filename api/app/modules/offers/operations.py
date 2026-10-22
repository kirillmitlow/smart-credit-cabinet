"""Область компании для HTTP-операции над предложением или договором."""

from uuid import UUID

from sqlalchemy import select

from app.modules import applications
from app.modules.offers.models import Contract, Offer
from app.shared import db, operations


def scope(kind: str, resource_id: UUID) -> operations.Scope | None:
    with db.transaction() as session:
        application_id = (
            session.scalar(select(Contract.application_id).where(Contract.id == resource_id))
            if kind == "contracts"
            else session.scalar(select(Offer.application_id).where(Offer.id == resource_id))
        )
    return applications.operation_scope(application_id) if application_id is not None else None
