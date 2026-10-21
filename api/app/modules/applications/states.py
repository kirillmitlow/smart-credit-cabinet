"""Стейт-машина заявки (20-02, D-055): 14 статусов и таблица разрешённых переходов.

Таблица — единственный источник правды: диаграмма в 20-02 сверяется с ней тестом.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHECKING = "CHECKING"
    NEEDS_INFO = "NEEDS_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    COUNTER_OFFER = "COUNTER_OFFER"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    SIGNED = "SIGNED"
    DISBURSING = "DISBURSING"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class Actor(StrEnum):
    CLIENT = "CLIENT"
    SYSTEM = "SYSTEM"
    UNDERWRITER = "UNDERWRITER"


S = Status
TERMINAL = frozenset({S.DISBURSED, S.REJECTED, S.WITHDRAWN, S.EXPIRED})
# «В работе»: у компании одновременно не больше одной такой заявки (DUPLICATE_APPLICATION)
IN_PROGRESS = frozenset(set(Status) - TERMINAL - {S.DRAFT})

TRANSITIONS: dict[tuple[Status, Status], Actor] = {
    (S.DRAFT, S.SUBMITTED): Actor.CLIENT,
    (S.SUBMITTED, S.CHECKING): Actor.SYSTEM,
    (S.CHECKING, S.NEEDS_INFO): Actor.SYSTEM,
    (S.CHECKING, S.MANUAL_REVIEW): Actor.SYSTEM,
    (S.CHECKING, S.APPROVED): Actor.SYSTEM,
    (S.CHECKING, S.COUNTER_OFFER): Actor.SYSTEM,
    (S.CHECKING, S.REJECTED): Actor.SYSTEM,
    (S.NEEDS_INFO, S.CHECKING): Actor.CLIENT,
    (S.MANUAL_REVIEW, S.APPROVED): Actor.UNDERWRITER,
    (S.MANUAL_REVIEW, S.COUNTER_OFFER): Actor.UNDERWRITER,
    (S.MANUAL_REVIEW, S.REJECTED): Actor.UNDERWRITER,
    (S.MANUAL_REVIEW, S.NEEDS_INFO): Actor.UNDERWRITER,
    (S.MANUAL_REVIEW, S.CHECKING): Actor.UNDERWRITER,
    (S.APPROVED, S.OFFER_ACCEPTED): Actor.CLIENT,
    (S.COUNTER_OFFER, S.OFFER_ACCEPTED): Actor.CLIENT,
    (S.COUNTER_OFFER, S.CHECKING): Actor.CLIENT,
    (S.OFFER_ACCEPTED, S.SIGNED): Actor.SYSTEM,
    (S.SIGNED, S.DISBURSING): Actor.SYSTEM,
    (S.DISBURSING, S.DISBURSED): Actor.SYSTEM,
    (S.SUBMITTED, S.WITHDRAWN): Actor.CLIENT,
    (S.CHECKING, S.WITHDRAWN): Actor.CLIENT,
    (S.NEEDS_INFO, S.WITHDRAWN): Actor.CLIENT,
    (S.MANUAL_REVIEW, S.WITHDRAWN): Actor.CLIENT,
    (S.APPROVED, S.WITHDRAWN): Actor.CLIENT,
    (S.COUNTER_OFFER, S.WITHDRAWN): Actor.CLIENT,
    (S.OFFER_ACCEPTED, S.WITHDRAWN): Actor.CLIENT,
    (S.NEEDS_INFO, S.EXPIRED): Actor.SYSTEM,
    (S.APPROVED, S.EXPIRED): Actor.SYSTEM,
    (S.COUNTER_OFFER, S.EXPIRED): Actor.SYSTEM,
}


def is_allowed(source: Status, target: Status, actor: Actor) -> bool:
    return TRANSITIONS.get((source, target)) is actor


def mermaid_edges() -> set[tuple[str, str]]:
    return {(a.value, b.value) for a, b in TRANSITIONS}


# Действия клиента, которые интерфейс показывает кнопками (allowedActions)
CLIENT_ACTIONS: dict[Status, tuple[str, ...]] = {
    S.DRAFT: ("EDIT_DRAFT", "SUBMIT", "DELETE_DRAFT"),
    S.SUBMITTED: ("WITHDRAW",),
    S.CHECKING: ("WITHDRAW",),
    S.NEEDS_INFO: ("RESPOND", "WITHDRAW"),
    S.MANUAL_REVIEW: ("WITHDRAW",),
    S.APPROVED: ("ACCEPT_OFFER", "WITHDRAW"),
    S.COUNTER_OFFER: ("ACCEPT_OFFER", "WITHDRAW"),
    S.OFFER_ACCEPTED: ("SIGN", "WITHDRAW"),
}
