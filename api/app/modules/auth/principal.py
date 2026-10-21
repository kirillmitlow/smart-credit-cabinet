"""Principal — кто спрашивает. Остальные модули видят только его, не сессию и не cookie (50-04)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class Zone(StrEnum):
    CLIENT = "client"
    BANK = "bank"


@dataclass(frozen=True)
class Membership:
    company_id: UUID
    role: str  # DIRECTOR | ACCOUNTANT | GUARANTOR
    permissions: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: str  # CLIENT | UNDERWRITER | ADMIN
    zone: Zone
    display_name: str
    person_inn: str | None = None
    memberships: tuple[Membership, ...] = ()
    active_company_id: UUID | None = None
    level: str | None = None  # L1 | L2 для банка
    session_id: str = field(default="", repr=False)

    def membership(self, company_id: UUID) -> Membership | None:
        return next((m for m in self.memberships if m.company_id == company_id), None)

    def can_access(self, company_id: UUID) -> bool:
        return self.membership(company_id) is not None
