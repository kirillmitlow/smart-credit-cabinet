"""Реестр правил T-126; ошибки сохраняют код правила и русское объяснение."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.common.admin import AdminHandler
from app.common.problems import ProblemException
from app.roles.bank_core.admin import BankCoreAdminHandler
from app.roles.bank_core.schemas import BankCoreBody
from app.roles.bki.admin import BkiAdminHandler
from app.roles.bki.schemas import BkiSubjectBody
from app.roles.registry.admin import RegistryHandler
from app.roles.registry.schemas import RegistryBody
from app.roles.scenarios import consistency_credit as credit
from app.roles.scenarios import consistency_finance as finance
from app.roles.scenarios import consistency_subjects as subjects
from app.roles.scenarios.config import ScenarioSettings
from app.roles.scenarios.consistency_common import Context, require
from app.roles.scenarios.debt_history import Trajectory
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.tax.admin import TaxHandler
from app.roles.tax.schemas import TaxBody


def body_schemas(c: Context) -> None:
    inn = c.identity["inn"]
    bodies: list[tuple[str, dict[str, Any], str, type[BaseModel], AdminHandler[Any]]] = [
        (inn, c.data, "registry", RegistryBody, RegistryHandler()),
        (inn, c.data, "tax", TaxBody, TaxHandler()),
        (inn, c.data, "bankCore", BankCoreBody, BankCoreAdminHandler()),
    ]
    for entry in c.data["bki"]:
        bodies.append((entry["inn"], entry, "body", BkiSubjectBody, BkiAdminHandler()))
    for entry in c.data["bankSubjects"]:
        require(
            isinstance(entry, dict) and "inn" in entry and "body" in entry,
            "bankSubjects[]: нужны inn и body",
        )
        bodies.append((entry["inn"], entry, "body", BankCoreBody, BankCoreAdminHandler()))
    for subject_inn, target, key, model, handler in bodies:
        try:
            body = model.model_validate(target[key], extra="forbid")
            if isinstance(body, BankCoreBody):
                BankCoreAdminHandler().check(subject_inn, body, bank_bik=c.settings.bank_bik)
            else:
                handler.check(subject_inn, body)
        except ProblemException as exc:
            raise ValueError(exc.detail) from exc
        except ValueError as exc:
            raise ValueError(f"Тело {key} у {subject_inn} не прошло проверку схемы: {exc}") from exc
        target[key] = body.model_dump(mode="json", by_alias=True)


def bank_subjects(c: Context) -> None:
    known = {p["inn"] for p in c.identity["persons"]} - {c.identity["inn"]}
    actual = [entry["inn"] for entry in c.data["bankSubjects"]]
    require(len(actual) == len(set(actual)), "В bankSubjects один участник указан дважды")
    require(set(actual) <= known, f"Неизвестные участники АБС: {set(actual) - known}")
    for entry in c.data["bankSubjects"]:
        require(
            not any(entry["body"][k] for k in ("customer", "accounts", "turnover", "loans")),
            f"Для физлица {entry['inn']} разрешены только сведения комплаенса",
        )


def loan_location(c: Context) -> None:
    require(
        not c.spec.active_loans and not c.spec.closed_loans,
        "activeLoans/closedLoans задаются внутри bki.company, bki.director или bki.owner; "
        "укажите субъекта, чтобы кредиты не были проигнорированы",
    )


@dataclass(frozen=True)
class Rule:
    code: str
    check: Callable[[Context], None]


RULES = (
    Rule("LOAN_LOCATION", loan_location),
    Rule("BODY_SCHEMAS", body_schemas),
    Rule("FORM_DATA", subjects.form_data),
    Rule("COMPANY_CARD", subjects.company_card),
    Rule("LLC_SHARES", subjects.llc_shares),
    Rule("ROLE_IDENTITIES", subjects.role_identities),
    Rule("BKI_IDENTITY", subjects.bki_identity),
    Rule("BKI_COMPANY_AGE", subjects.bki_company_age),
    Rule("BANK_SUBJECTS", bank_subjects),
    Rule("REPORT_YEARS", finance.report_years),
    Rule("REPORT_BALANCE", finance.report_balance),
    Rule("PB_REVENUE", finance.pb_revenue),
    Rule("TURNOVER_REVENUE", finance.turnover_revenue),
    Rule("TURNOVER_WINDOW", finance.turnover_window),
    Rule("CUSTOMER_AGE", finance.customer_age),
    Rule("NON_CUSTOMER_DATA", finance.non_customer_data),
    Rule("SME_CATEGORY", finance.sme_category),
    Rule("REGIME_LIMITS", finance.regime_limits),
    Rule("LOAN_PAYMENT", credit.loan_payment),
    Rule("LOAN_UIDS", credit.loan_uids),
    Rule("LOAN_DATES", credit.loan_dates),
    Rule("BANKRUPTCY_MATCH", credit.bankruptcy_match),
    Rule("BANKRUPT_STATUS", credit.bankrupt_status),
    Rule("BANKRUPTCY_DATES", credit.bankruptcy_dates),
    Rule("OUR_BANK_UID", credit.our_bank_uid),
    Rule("ACCOUNT_BLOCK", credit.account_block),
    Rule("CONTRACTS", credit.contracts),
    Rule("STATEMENT_DEBT", finance.statement_debt),
)


def validate_expanded(
    spec: ScenarioSpec,
    data: dict[str, Any],
    today: date,
    settings: ScenarioSettings,
    code: str,
    history: dict[str, Trajectory],
) -> dict[str, Any]:
    context = Context(spec, data, today, settings, code, history)
    for rule in RULES:
        try:
            rule.check(context)
        except ValueError as exc:
            raise ValueError(f"{rule.code}: {exc}") from exc
    entity = data["registry"]["entity"]
    if entity:
        data["identity"]["status"] = entity["status"]["code"]
    return data
