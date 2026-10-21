"""T-230/T-235: одиночные сбои моков (`X-Mock-Scenario` на первый запрос) и поведение адаптера.

Режим мока не меняем: сбой касается ровно одного запроса, повтор идёт без заголовка (8.2).
Полный прогон всех режимов на двух адаптерах и счётчики на стороне мока — задача T-238.
"""

# ruff: noqa: PT018 — короткие составные assert читаются лучше, чем разбитые
from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.integrations import BkiConsent, BureauSubject, Integrations, Ok
from app.shared import clock
from tests.contract.conftest import ListJournal, Persona

pytestmark = [pytest.mark.contract, pytest.mark.chaos]

PersonaFactory = Callable[[str], Persona]
WithFailure = Callable[[str], Integrations]


def test_registry_error_then_success(
    live_with_first_failure: WithFailure, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("sokolova")
    result = live_with_first_failure("ERROR").registry.get_company(p.inn)
    assert isinstance(result, Ok) and result.data is not None
    assert [(r.attempt, r.status_code) for r in journal.records] == [(1, 503), (2, 200)]
    assert journal.records[0].error_code == "SERVICE_UNAVAILABLE"  # код проблемы мока


def test_tax_slow_exceeds_timeout_then_retry_succeeds(
    live_with_first_failure: WithFailure, persona: PersonaFactory, journal: ListJournal
) -> None:
    p = persona("romashka")
    result = live_with_first_failure("SLOW:2600").tax.get_sme_status(p.inn)  # таймаут налоговой 2 с
    assert isinstance(result, Ok)
    assert [(r.attempt, r.error_code) for r in journal.records] == [(1, "TIMEOUT"), (2, None)]


def test_bureau_lost_response_replays_same_report_without_second_inquiry(
    live_with_first_failure: WithFailure, persona: PersonaFactory, journal: ListJournal
) -> None:
    """Мок выполнил запрос и оборвал связь: повтор с тем же ключом возвращает тот же отчёт."""
    p = persona("romashka")
    director = p.person("director")
    subject = BureauSubject(
        "PERSON",
        director["inn"],
        last_name=director["lastName"],
        first_name=director["firstName"],
        middle_name=director.get("middleName"),
    )
    consent = BkiConsent(
        f"cns_{uuid4().hex[:8]}", subject.inn, clock.now() - timedelta(minutes=1),
        clock.today() + timedelta(days=180), "LOAN_APPLICATION", "SIMPLE_ESIGN", subject.inn,
        "bki-consent-v1",
    )  # fmt: skip
    live = live_with_first_failure("LOST_RESPONSE")
    result = live.credit_bureau.request_report(consent, subject, f"APP-CT-{uuid4().hex[:8]}")
    assert isinstance(result, Ok)
    assert result.snapshot_meta.replayed is True
    assert [(r.attempt, r.error_code, r.idempotent_replayed) for r in journal.records] == [
        (1, "CONNECTION_ERROR", False),
        (2, None, True),
    ]
    own_before = sum(i.is_own for i in result.data.inquiries)

    # Следующий запрос с другим ключом добавляет ровно один свой запрос: потерянный не задвоился
    again = live.credit_bureau.request_report(consent, subject, f"APP-CT-{uuid4().hex[:8]}")
    assert isinstance(again, Ok)
    assert sum(i.is_own for i in again.data.inquiries) == own_before + 1
