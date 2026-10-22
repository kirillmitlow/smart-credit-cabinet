"""Шаг 2 конвейера: бесплатные источники параллельно (T-272, 50-05 Q-054 вариант А, 30-01).

Синхронные адаптеры + пул из 4 потоков: в худшем режиме `SLOW` шаг укладывается в ~10 с, а не в
сумму всех вызовов. Реестр идёт первым, остальное стартует сразу; от карточки реестра зависят
только ЕФРСБ по участникам, комплаенс и (для самозанятого) НПД: они запускаются, как только
карточка пришла. Адаптеры не бросают исключений: недоступность — это `SourceUnavailable`.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import UUID

import structlog

from app.modules.decisioning.types import Product
from app.modules.integrations import (
    CompanyRecord,
    Integrations,
    Ok,
    Result,
    ScreeningSubject,
)
from app.modules.pipeline import facts
from app.modules.pipeline.snapshots import Collected

log = structlog.get_logger("app.pipeline.sources")

POOL_SIZE = 4
TURNOVER_MONTHS = 24


def _job(resource: str, inn: str, call: Callable[[], Result[Any]]) -> Callable[[], Collected]:
    return lambda: Collected(resource, inn, call())


def collect_free_sources(
    integrations: Integrations,
    *,
    application_id: UUID,
    applicant_inn: str,
    product: Product,
) -> list[Collected]:
    """Свежие ответы реестра, ЕФРСБ, ФНС, ЕИС (для CONTRACT), комплаенса и АБС (без кэша)."""
    aid, inn = application_id, applicant_inn
    reg, tax, core = integrations.registry, integrations.tax, integrations.bank_core
    first = _job(facts.REGISTRY, inn, lambda: reg.get_company(inn, application_id=aid))
    independent = [
        _job(facts.TAX_PROFILE, inn, lambda: tax.get_tax_profile(inn, application_id=aid)),
        _job(facts.FINANCIALS, inn, lambda: tax.get_financials(inn, application_id=aid)),
        _job(facts.SME, inn, lambda: tax.get_sme_status(inn, application_id=aid)),
        _job(facts.BLOCKS, inn, lambda: tax.get_account_blocks(inn, application_id=aid)),
        _job(facts.CUSTOMER, inn, lambda: core.get_customer(inn, application_id=aid)),
        # TODO(T-260): обороты читаем только при согласии на обороты; пока согласие этого вида не выдаёт applications
        _job(
            facts.TURNOVER,
            inn,
            lambda: core.get_turnover(inn, TURNOVER_MONTHS, application_id=aid),
        ),
        _job(facts.LOANS, inn, lambda: core.get_loans(inn, application_id=aid)),
    ]
    if product == Product.CONTRACT:
        independent.append(
            _job(facts.CONTRACTS, inn, lambda: tax.get_gov_contracts(inn, application_id=aid))
        )

    collected: list[Collected] = []
    with ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="pipeline-src") as pool:
        registry_future = pool.submit(first)
        futures: list[Future[Collected]] = [pool.submit(job) for job in independent]
        registry_item = registry_future.result()
        collected.append(registry_item)
        card = _card(registry_item)
        subjects = facts.screening_subjects(inn, card)
        dependent = [_bankruptcy_job(integrations, aid, s.inn) for s in subjects]
        screening = _screening_job(integrations, aid, inn, subjects, card)
        if screening is not None:
            dependent.append(screening)
        if isinstance(registry_item.result, Ok) and registry_item.result.data is None:
            # Нет в ЕГРЮЛ/ЕГРИП: возможно, самозанятый (допуск, 30-01 шаг 1)
            dependent.append(
                _job(facts.NPD, inn, lambda: tax.get_self_employed_status(inn, application_id=aid))
            )
        futures.extend(pool.submit(job) for job in dependent)
        collected.extend(f.result() for f in futures)
    return collected


def _bankruptcy_job(
    integrations: Integrations, application_id: UUID, inn: str
) -> Callable[[], Collected]:
    registry = integrations.registry
    return _job(
        facts.BANKRUPTCIES,
        inn,
        lambda: registry.get_bankruptcies(inn, application_id=application_id),
    )


def _card(item: Collected) -> CompanyRecord | None:
    result = item.result
    return result.data if isinstance(result, Ok) else None


def _screening_job(
    integrations: Integrations,
    application_id: UUID,
    inn: str,
    subjects: list[facts.Subject],
    card: CompanyRecord | None,
) -> Callable[[], Collected] | None:
    """Комплаенс одним вызовом. Для ООО без карточки (нет директора) проверять нечего."""
    is_company = len(inn) == 10
    if is_company and (card is None or not any(s.role.value == "DIRECTOR" for s in subjects)):
        log.info("compliance_skipped", reason="нет директора в карточке реестра")
        return None
    request = [ScreeningSubject(s.inn, s.compliance_role) for s in subjects]
    bank = integrations.bank_core
    return _job(facts.COMPLIANCE, inn, lambda: bank.screen(request, application_id=application_id))
