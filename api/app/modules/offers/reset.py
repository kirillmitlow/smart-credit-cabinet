"""Сброс демо-данных модуля (T-371, 50-04): очистка его таблиц; справочники не трогаем."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.shared.resets import (
    Persona,
    delete_owned,
    owned_ids,
    register_persona_reset,
    register_reset,
    truncate,
)

TABLES = (
    "offers",
    "offer_variants",
    "contracts",
    "signatures",
)


def reset_demo_data(session: Session) -> None:
    truncate(session, *TABLES)


register_reset("offers", reset_demo_data)


def prepare_persona(session: Session, scope: Persona) -> None:
    for table in ("offers", "contracts"):
        scope.add(
            table, owned_ids(session, "offers", table, "application_id", scope.ids("applications"))
        )


def reset_persona(session: Session, scope: Persona) -> None:
    delete_owned(session, "offers", "signatures", "contract_id", scope.ids("contracts"))
    delete_owned(session, "offers", "contracts", "id", scope.ids("contracts"))
    delete_owned(session, "offers", "offer_variants", "offer_id", scope.ids("offers"))
    delete_owned(session, "offers", "offers", "id", scope.ids("offers"))


register_persona_reset("offers", reset_persona, priority=40, prepare=prepare_persona)
