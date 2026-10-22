"""Шаг 3–4: БКИ по всем субъектам заявки до расчёта решения (T-273, D-090, D-077).

План (в базе, без сети): по каждому субъекту — переиспользовать свежий отчёт этой заявки,
запросить новый или не звать вовсе (нет действующего согласия). Запросы идут параллельно, ключ
идемпотентности `bki-report:{заявка}:{ИНН}` не даёт платить дважды при повторе запуска.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.modules.integrations import BureauSubject, Integrations, SourceUnavailable
from app.modules.pipeline import facts
from app.modules.pipeline.consents import ConsentView, valid_consent
from app.modules.pipeline.snapshots import CONSENT_ERROR_PREFIX, Collected, find_reusable_report

log = structlog.get_logger("app.pipeline.bureau")

POOL_SIZE = 4


@dataclass(frozen=True, slots=True)
class BureauPlan:
    to_request: tuple[tuple[facts.Subject, ConsentView], ...]
    reused: tuple[facts.Subject, ...]
    no_consent: tuple[facts.Subject, ...]


def plan_bureau(
    session: Session,
    application_id: UUID,
    subjects: Sequence[facts.Subject],
    consents: Sequence[ConsentView],
) -> BureauPlan:
    request: list[tuple[facts.Subject, ConsentView]] = []
    reused: list[facts.Subject] = []
    refused: list[facts.Subject] = []
    for subject in subjects:
        if find_reusable_report(session, application_id, subject.inn) is not None:
            reused.append(subject)
            continue
        consent = valid_consent(consents, subject.inn)
        if consent is None:
            refused.append(subject)
        else:
            request.append((subject, consent))
    return BureauPlan(tuple(request), tuple(reused), tuple(refused))


def _bureau_subject(subject: facts.Subject) -> BureauSubject:
    if not subject.is_person:
        return BureauSubject("LEGAL_ENTITY", subject.inn, name=subject.name, ogrn=subject.ogrn)
    last, first, middle = facts.split_person_name(subject.name)
    return BureauSubject(
        "PERSON", subject.inn, last_name=last, first_name=first, middle_name=middle
    )


def request_reports(
    integrations: Integrations, plan: BureauPlan, *, application_id: UUID, application_ref: str
) -> list[Collected]:
    """Платные запросы параллельно. Адаптер сам откажет без действующего согласия, сети не будет."""

    def one(subject: facts.Subject, consent: ConsentView) -> Collected:
        result = integrations.credit_bureau.request_report(
            consent.to_bki(),
            _bureau_subject(subject),
            application_ref,
            application_id=application_id,
        )
        return Collected(facts.BKI_REPORT, subject.inn, result)

    if not plan.to_request:
        return []
    with ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="pipeline-bki") as pool:
        futures = [pool.submit(one, s, c) for s, c in plan.to_request]
        return [f.result() for f in futures]


def inns_without_consent(
    records: facts.Records, subjects: Sequence[facts.Subject]
) -> frozenset[str]:
    """Субъекты, по которым БКИ не запрашивался из-за согласия: не было вызова либо отказ по согласию."""
    out: set[str] = set()
    for s in subjects:
        rec = records.get(facts.BKI_REPORT, s.inn)
        if rec is None or (rec.error_code or "").startswith(CONSENT_ERROR_PREFIX):
            out.add(s.inn)
    return frozenset(out)


def is_consent_refusal(item: Collected) -> bool:
    result = item.result
    return isinstance(result, SourceUnavailable) and (result.error_code or "").startswith(
        CONSENT_ERROR_PREFIX
    )
