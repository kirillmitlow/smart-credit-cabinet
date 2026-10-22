"""Согласия на запрос в БКИ: переходник к модулю `applications` (T-273, T-260, 20-04, D-090).

Согласия подписывает и хранит `applications` (отдельная задача T-260). Конвейер читает их одной
функцией `bki_consents(session, application_id)`. Пока её нет в `applications`, здесь пусто:
БКИ не вызывается, заявка уходит в `NEEDS_INFO(DATA_INCOMPLETE)`. Это безопасная сторона.
TODO(T-260): когда `bki_consents` появится в `applications`, переходник заработает сам; тесты
подставляют свою функцию через `set_consents_provider`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.modules import applications
from app.modules.integrations import BkiConsent
from app.shared import clock

log = structlog.get_logger("app.pipeline.consents")

PURPOSE = "LOAN_APPLICATION"
# Допуск часов между контейнерами, как в адаптере БКИ (моки 2.5)
CLOCK_SKEW = timedelta(minutes=5)

# Что показать клиенту, если согласия нет (идёт в `DATA_INCOMPLETE`)
CONSENT_LABELS = {
    "COMPANY": "на запрос в БКИ (компания)",
    "DIRECTOR": "на запрос в БКИ (руководитель)",
    "GUARANTOR": "на запрос в БКИ (поручитель)",
}


@dataclass(frozen=True, slots=True)
class ConsentView:
    consent_id: str
    subject_inn: str
    role: str
    signed_at: datetime
    valid_until: date
    purpose: str
    sign_method: str = "SIMPLE_ESIGN"
    signer_inn: str | None = None
    text_version: str = "bki-consent-v1"

    def is_valid(self) -> bool:
        return (
            self.purpose == PURPOSE
            and self.valid_until >= clock.today()
            and self.signed_at <= clock.now() + CLOCK_SKEW
        )

    def to_bki(self) -> BkiConsent:
        return BkiConsent(
            consent_id=self.consent_id,
            subject_inn=self.subject_inn,
            signed_at=self.signed_at,
            valid_until=self.valid_until,
            purpose=self.purpose,
            sign_method=self.sign_method,
            signer_inn=self.signer_inn or self.subject_inn,
            text_version=self.text_version,
        )


Provider = Callable[[Session, UUID], Sequence[ConsentView]]
_provider: Provider | None = None


def set_consents_provider(provider: Provider | None) -> None:
    """Подмена источника согласий (тесты, пока T-260 не влит)."""
    global _provider
    _provider = provider


def _from_applications(session: Session, application_id: UUID) -> Sequence[ConsentView]:
    fetch: Any = getattr(applications, "bki_consents", None)
    if fetch is None:
        log.warning("bki_consents_unavailable", hint="applications.bki_consents (T-260) не влит")
        return ()
    return [
        ConsentView(
            consent_id=str(c.consent_id),
            subject_inn=c.subject_inn,
            role=str(getattr(c, "role", "")),
            signed_at=c.signed_at,
            valid_until=c.valid_until,
            purpose=c.purpose,
            sign_method=getattr(c, "sign_method", "SIMPLE_ESIGN"),
            signer_inn=getattr(c, "signer_inn", None),
            text_version=getattr(c, "text_version", "bki-consent-v1"),
        )
        for c in fetch(session, application_id)
    ]


def load_bki_consents(session: Session, application_id: UUID) -> Sequence[ConsentView]:
    return (_provider or _from_applications)(session, application_id)


def valid_consent(consents: Sequence[ConsentView], subject_inn: str) -> ConsentView | None:
    """Самое свежее действующее согласие этого субъекта на эту цель."""
    fitting = [c for c in consents if c.subject_inn == subject_inn and c.is_valid()]
    return max(fitting, key=lambda c: c.signed_at, default=None)
