"""Пользователи, вход по ИНН и одноразовому коду, роли, Principal. Документ: 50-04, 50-09, D-062.

Публичный интерфейс модуля — только то, что ниже.
"""

from app.modules.auth import (
    codes,
    reset,  # noqa: F401 — регистрирует сброс демо-данных (T-371)
    sessions,
)
from app.modules.auth.dependencies import (
    BankPrincipal,
    ClientPrincipal,
    current_bank,
    current_client,
    require,
)
from app.modules.auth.models import User
from app.modules.auth.principal import Membership, Principal, Zone
from app.modules.auth.service import by_person_inn, get, upsert_client

__all__ = [
    "BankPrincipal",
    "ClientPrincipal",
    "Membership",
    "Principal",
    "User",
    "Zone",
    "by_person_inn",
    "codes",
    "current_bank",
    "current_client",
    "get",
    "require",
    "sessions",
    "upsert_client",
]
