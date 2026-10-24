"""Перевод моделей адаптеров во вход `decide()` (R4, T-272, 30-01, 30-02).

Единственное место, где знают оба языка: «модели integrations» и «типы ядра». Чистые функции:
без сети, базы и часов. Недоступный источник превращается в `SourceStatus.UNAVAILABLE`, а
`Ok(None)` (404: не клиент, нет отчётности, нет в реестре) — в `NOT_FOUND`; ядро различает их.
Формул здесь нет: только раскладка полей (арифметика живёт в `decisioning`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules import decisioning as core
from app.modules import integrations as ext
from app.modules.decisioning.types import (
    ApplicantKind,
    Application,
    BankruptcyCase,
    BankruptcyCheck,
    BkiObligation,
    BkiReport,
    BkiSubject,
    Collateral,
    ComplianceData,
    ComplianceResult,
    ContractInfo,
    ContractsData,
    CustomerData,
    FinancialsData,
    FinancialYear,
    Founder,
    Guarantor,
    NpdData,
    OurLoan,
    Product,
    RegistryData,
    Snapshot,
    SourceMeta,
    SourceStatus,
    StatementData,
    SubjectRole,
    TaxData,
    TurnoverData,
    TurnoverMonth,
)

# ---------------------------------------------------------------- ресурсы и записи ответов

REGISTRY = "registry:company"
BANKRUPTCIES = "registry:bankruptcies"
TAX_PROFILE = "tax:profile"
FINANCIALS = "tax:financials"
SME = "tax:sme"
BLOCKS = "tax:blocks"
NPD = "tax:npd"
CONTRACTS = "tax:contracts"
CUSTOMER = "bank_core:customer"
TURNOVER = "bank_core:turnover"
LOANS = "bank_core:loans"
COMPLIANCE = "bank_core:compliance"
BKI_REPORT = "credit_bureau:report"
STATEMENT = "client_upload:statement"

_OK, _NOT_FOUND, _UNAVAILABLE = SourceStatus.OK, SourceStatus.NOT_FOUND, SourceStatus.UNAVAILABLE


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Один ответ источника: статус, дата данных, id снимка и разобранная модель адаптера."""

    resource: str
    subject_inn: str
    status: SourceStatus
    snapshot_id: str | None = None
    data_as_of: date | None = None
    data: Any = None
    error_code: str | None = None

    @property
    def meta(self) -> SourceMeta:
        return SourceMeta(self.status, self.data_as_of, self.snapshot_id)

    @property
    def usable(self) -> bool:
        return self.status == _OK and self.data is not None


class Records:
    """Ответы источников одного запуска, поиск по ресурсу и ИНН субъекта."""

    def __init__(self, records: Iterable[SourceRecord]) -> None:
        self._by_key = {(r.resource, r.subject_inn): r for r in records}

    def get(self, resource: str, inn: str) -> SourceRecord | None:
        return self._by_key.get((resource, inn))

    def all(self) -> list[SourceRecord]:
        return list(self._by_key.values())


# ---------------------------------------------------------------- субъекты


@dataclass(frozen=True, slots=True)
class Subject:
    """Участник заявки для ЕФРСБ, комплаенса и БКИ."""

    role: SubjectRole
    inn: str
    is_person: bool
    name: str | None = None
    share_percent: Decimal | None = None
    ogrn: str | None = None

    @property
    def compliance_role(self) -> str:
        if self.role == SubjectRole.COMPANY:
            return "IE" if self.is_person else "COMPANY"
        return self.role.value


_ROLE_PRIORITY = {SubjectRole.COMPANY: 0, SubjectRole.DIRECTOR: 1, SubjectRole.FOUNDER: 2}


def screening_subjects(applicant_inn: str, card: ext.CompanyRecord | None) -> list[Subject]:
    """ЕФРСБ и комплаенс: компания (ИП), директор и учредители-люди; один человек — одна роль."""
    is_ie = card.kind == "INDIVIDUAL_ENTREPRENEUR" if card else len(applicant_inn) == 12
    out: list[Subject] = [
        Subject(
            SubjectRole.COMPANY,
            applicant_inn,
            is_ie,
            card.name if card else None,
            ogrn=card.ogrn if card else None,
        )
    ]
    if card is not None and not is_ie:
        if card.director is not None and card.director.inn:
            out.append(
                Subject(SubjectRole.DIRECTOR, card.director.inn, True, card.director.full_name)
            )
        for founder in card.founders:
            if founder.kind == "PERSON" and founder.inn:
                share = Decimal(str(founder.share_percent)) if founder.share_percent else Decimal(0)
                out.append(
                    Subject(SubjectRole.FOUNDER, founder.inn, True, founder.full_name, share)
                )
    return _dedupe(out)


def bki_subjects(
    applicant_inn: str, card: ext.CompanyRecord | None, guarantor_inn: str | None
) -> list[Subject]:
    """БКИ: компания или ИП, директор (для ООО), поручитель. Учредители в отчётах БКИ не участвуют."""
    base = [s for s in screening_subjects(applicant_inn, card) if s.role != SubjectRole.FOUNDER]
    if guarantor_inn:
        base.append(Subject(SubjectRole.GUARANTOR, guarantor_inn, True))
    return _dedupe(base)


def _dedupe(subjects: Sequence[Subject]) -> list[Subject]:
    seen: dict[str, Subject] = {}
    for s in subjects:
        known = seen.get(s.inn)
        if known is None or _ROLE_PRIORITY.get(s.role, 9) < _ROLE_PRIORITY.get(known.role, 9):
            seen[s.inn] = s
    return list(seen.values())


def split_person_name(full_name: str | None) -> tuple[str | None, str | None, str | None]:
    """«Фамилия Имя Отчество» → части для запроса в БКИ."""
    parts = (full_name or "").split()
    return (
        parts[0] if parts else None,
        parts[1] if len(parts) > 1 else None,
        " ".join(parts[2:]) or None if len(parts) > 2 else None,
    )


# ---------------------------------------------------------------- заявка


def build_application(
    application_id: str,
    version_data: dict[str, Any],
    *,
    unsigned_consents: Sequence[str] = (),
    guarantor_consent_signed: bool = False,
) -> Application:
    """Заявка из `application_versions.data`; ключи анкеты читаются из `draft` (см. Q-147)."""
    draft: dict[str, Any] = version_data.get("draft") or {}
    product_code = version_data.get("productCode")
    amount = version_data.get("amountRub")
    term = version_data.get("termMonths")
    missing = [
        name
        for name, value in (
            ("product_code", product_code),
            ("amount_rub", amount),
            ("term_months", term),
        )
        if value is None
    ]
    collateral_raw = draft.get("collateral")
    collateral = (
        Collateral(str(collateral_raw.get("description", "")), int(collateral_raw["valueRub"]))
        if isinstance(collateral_raw, dict) and collateral_raw.get("valueRub") is not None
        else None
    )
    guarantor_raw = draft.get("guarantor")
    guarantor = (
        Guarantor(str(guarantor_raw["inn"]), guarantor_consent_signed)
        if isinstance(guarantor_raw, dict) and guarantor_raw.get("inn")
        else None
    )
    declared = draft.get("declaredMonthlyRevenueRub")
    return Application(
        application_id=application_id,
        product=Product(product_code) if product_code else Product.EXPRESS,
        amount_rub=int(amount or 0),
        term_months=int(term or 0),
        collateral=collateral,
        guarantor=guarantor,
        contract_registry_number=draft.get("contractRegistryNumber"),
        declared_monthly_revenue_rub=int(declared) if declared is not None else None,
        director_name_in_form=draft.get("directorName"),
        missing_fields=tuple(missing),
        unsigned_consents=tuple(unsigned_consents),
    )


def guarantor_inn(version_data: dict[str, Any]) -> str | None:
    raw = (version_data.get("draft") or {}).get("guarantor")
    return str(raw["inn"]) if isinstance(raw, dict) and raw.get("inn") else None


# ---------------------------------------------------------------- отдельные источники


def _missing(rec: SourceRecord | None, default: SourceStatus) -> SourceMeta:
    return rec.meta if rec is not None else SourceMeta(default)


def registry_data(rec: SourceRecord | None) -> RegistryData:
    if rec is None:
        return RegistryData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return RegistryData(rec.meta)
    card: ext.CompanyRecord = rec.data
    return RegistryData(
        meta=rec.meta,
        kind=ApplicantKind(card.kind),
        inn=card.inn,
        registration_date=card.registration_date,
        status_code=card.status_code,
        okved_main=card.okved_main or "",
        director_name=card.director.full_name if card.director else None,
        director_inn=card.director.inn if card.director else None,
        founders=tuple(
            Founder(
                name=f.full_name or "",
                inn=f.inn or "",
                share_percent=Decimal(str(f.share_percent or 0)),
                is_person=f.kind == "PERSON",
            )
            for f in card.founders
        ),
    )


def npd_data(rec: SourceRecord | None) -> NpdData:
    if rec is None:
        return NpdData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return NpdData(rec.meta)
    status: ext.SelfEmployedStatus = rec.data
    return NpdData(rec.meta, status.is_self_employed)


def _cases(cases: Iterable[ext.BankruptcyCase]) -> tuple[BankruptcyCase, ...]:
    return tuple(
        BankruptcyCase(c.case_number, c.stage, c.started_at, c.completed_at) for c in cases
    )


def bankruptcy_checks(records: Records, subjects: Sequence[Subject]) -> tuple[BankruptcyCheck, ...]:
    out: list[BankruptcyCheck] = []
    for s in subjects:
        rec = records.get(BANKRUPTCIES, s.inn)
        share = s.share_percent if s.role == SubjectRole.FOUNDER else None
        if rec is None:
            out.append(
                BankruptcyCheck(s.inn, s.role, share, SourceMeta(SourceStatus.NOT_REQUESTED))
            )
        elif not rec.usable:
            out.append(BankruptcyCheck(s.inn, s.role, share, rec.meta))
        else:
            out.append(BankruptcyCheck(s.inn, s.role, share, rec.meta, _cases(rec.data)))
    return tuple(out)


def tax_data(
    profile: SourceRecord | None, sme: SourceRecord | None, blocks: SourceRecord | None
) -> TaxData:
    if profile is None:
        return TaxData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not profile.usable:
        return TaxData(profile.meta)
    p: ext.TaxProfile = profile.data
    category = None
    if sme is not None and sme.usable:
        sme_status: ext.SmeStatus = sme.data
        category = sme_status.category if sme_status.in_registry else None
    blocked = bool(blocks is not None and blocks.usable and blocks.data)
    return TaxData(
        meta=profile.meta,
        regimes=tuple(dict.fromkeys(r.code for r in p.regimes)),
        tax_debt_rub=p.tax_debt_rub,
        penalties_rub=p.penalties_rub,
        fines_rub=p.fines_rub,
        offenses_count=p.offenses_count,
        mass_address=p.mass_address,
        mass_director=p.mass_director,
        mass_founder=p.mass_founder,
        account_block_active=blocked,
        sme_category=category,
    )


def financials_data(rec: SourceRecord | None) -> FinancialsData:
    if rec is None:
        return FinancialsData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return FinancialsData(rec.meta)
    f: ext.Financials = rec.data
    years: list[FinancialYear] = []
    revenue = f.line("2110")
    if revenue is not None:
        years.append(FinancialYear(f.year, revenue, f.line("2400") or 0, f.line("2330") or 0))
    previous = f.lines.get("2110")
    if previous is not None and previous.previous is not None:
        net = f.lines.get("2400")
        interest = f.lines.get("2330")
        years.append(
            FinancialYear(
                f.year - 1,
                previous.previous,
                (net.previous if net and net.previous is not None else 0),
                (interest.previous if interest and interest.previous is not None else 0),
            )
        )
    return FinancialsData(rec.meta, tuple(years))


def contracts_data(rec: SourceRecord | None) -> ContractsData:
    if rec is None:
        return ContractsData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return ContractsData(rec.meta)
    contracts: tuple[ext.GovContract, ...] = rec.data
    return ContractsData(
        rec.meta,
        tuple(
            ContractInfo(c.registry_number, c.price_rub, c.paid_rub, c.status, c.payment_deadline)
            for c in contracts
        ),
    )


def compliance_data(rec: SourceRecord | None, subjects: Sequence[Subject]) -> ComplianceData:
    if rec is None:
        return ComplianceData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return ComplianceData(rec.meta)
    result: ext.ComplianceResult = rec.data
    role_by_inn = {s.inn: s.role for s in subjects}
    return ComplianceData(
        rec.meta,
        tuple(
            ComplianceResult(r.inn, role_by_inn.get(r.inn, _role(r.role)), r.aml_listed)
            for r in result.results
        ),
    )


def _role(raw: str) -> SubjectRole:
    return SubjectRole.COMPANY if raw == "IE" else SubjectRole(raw)


def customer_data(
    customer: SourceRecord | None,
    loans: SourceRecord | None,
    bki_payments: dict[str, int],
) -> CustomerData:
    """Клиент ли банка и его кредиты у нас. Платёж по кредиту берём из БКИ по `contract_uid`."""
    if customer is None:
        return CustomerData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not customer.usable:
        return CustomerData(customer.meta)
    c: ext.Customer = customer.data
    our: list[OurLoan] = []
    if loans is not None and loans.usable:
        for loan in loans.data:
            if loan.status != "ACTIVE":
                continue
            our.append(
                OurLoan(loan.contract_uid, _our_payment(loan, bki_payments), loan.outstanding_rub)
            )
    return CustomerData(customer.meta, True, c.customer_since, tuple(our))


def _our_payment(loan: ext.OurLoan, bki_payments: dict[str, int]) -> int:
    if loan.contract_uid in bki_payments:
        return bki_payments[loan.contract_uid]
    # TODO(T-272): в БКИ кредита нет — оценка по графику ядра (аннуитет) для кредитов с известными условиями
    if (
        loan.kind == "LOAN"
        and loan.amount_rub
        and loan.rate_percent is not None
        and loan.term_months
    ):
        schedule = core.build_schedule(
            loan.amount_rub, Decimal(str(loan.rate_percent)) / 100, loan.term_months
        )
        return schedule[0].payment
    return 0


def turnover_data(rec: SourceRecord | None) -> TurnoverData:
    if rec is None:
        return TurnoverData(SourceMeta(SourceStatus.NOT_REQUESTED))
    if not rec.usable:
        return TurnoverData(rec.meta)
    t: ext.Turnover = rec.data
    return TurnoverData(
        rec.meta,
        tuple(
            TurnoverMonth(
                _month_start(m.month), m.incoming_net_rub, m.outgoing_rub, m.counterparties_in
            )
            for m in t.months
        ),
    )


def statement_data(rec: SourceRecord | None) -> StatementData:
    if rec is None:
        return StatementData()
    if not rec.usable:
        return StatementData(rec.meta)
    payload: dict[str, Any] = rec.data
    return StatementData(
        rec.meta,
        tuple(
            TurnoverMonth(_month_start(row["month"]), row["incomingRub"], row["outgoingRub"], None)
            for row in payload["months"]
        ),
        owner_inn_matches=payload["inn"] == rec.subject_inn,
    )


def _month_start(value: str) -> date:
    year, month = value.split("-")[:2]
    return date(int(year), int(month), 1)


def bki_report(history: ext.CreditHistory) -> BkiReport:
    s = history.summary
    return BkiReport(
        has_history=history.has_history,
        history_months=s.history_length_months,
        active_obligations=s.active_obligations,
        closed_obligations=s.closed_obligations,
        total_debt_rub=s.total_debt_rub,
        monthly_payments_rub=s.monthly_payments_rub,
        contingent_liabilities_rub=s.contingent_liabilities_rub,
        current_overdue_rub=s.current_overdue_rub,
        current_overdue_days=s.current_overdue_days,
        max_overdue_days_24m=s.max_overdue_days_24m,
        restructurings_24m=s.restructurings_24m,
        inquiries_30d_excl_own=s.inquiries_30d_excluding_own,
        rejected_90d_excl_own=s.rejected_applications_90d_excluding_own,
        obligations=tuple(
            BkiObligation(o.uid, o.kind, o.status, o.monthly_payment_rub or 0, o.balance_rub)
            for o in history.obligations
        ),
        bankruptcies=_cases(history.bankruptcies),
    )


def bki_payments_by_uid(records: Records, subjects: Sequence[Subject]) -> dict[str, int]:
    """Платежи по обязательствам компании из БКИ: ими же оцениваем наши кредиты."""
    out: dict[str, int] = {}
    for s in subjects:
        if s.role != SubjectRole.COMPANY:
            continue
        rec = records.get(BKI_REPORT, s.inn)
        if rec is not None and rec.usable:
            history: ext.CreditHistory = rec.data
            out.update({o.uid: o.monthly_payment_rub or 0 for o in history.obligations})
    return out


def bki_subject_data(
    records: Records, subjects: Sequence[Subject], no_consent: frozenset[str]
) -> tuple[BkiSubject, ...]:
    """Субъекты БКИ. Нет согласия — `NOT_REQUESTED` (вызова не было), сбой — `UNAVAILABLE`."""
    out: list[BkiSubject] = []
    for s in subjects:
        rec = records.get(BKI_REPORT, s.inn)
        if s.inn in no_consent or rec is None:
            out.append(BkiSubject(s.role, s.inn, SourceMeta(SourceStatus.NOT_REQUESTED)))
        elif not rec.usable:
            out.append(BkiSubject(s.role, s.inn, rec.meta))
        else:
            history: ext.CreditHistory = rec.data
            if history.match_status == "NOT_FOUND":
                out.append(
                    BkiSubject(
                        s.role, s.inn, SourceMeta(_NOT_FOUND, rec.data_as_of, rec.snapshot_id)
                    )
                )
            else:
                out.append(BkiSubject(s.role, s.inn, rec.meta, bki_report(history)))
    return tuple(out)


# ---------------------------------------------------------------- единый снимок


def build_snapshot(
    records: Records,
    *,
    applicant_inn: str,
    product: Product,
    bki_no_consent: frozenset[str] = frozenset(),
    bki_subject_list: Sequence[Subject] = (),
) -> Snapshot:
    card_rec = records.get(REGISTRY, applicant_inn)
    card: ext.CompanyRecord | None = (
        card_rec.data if card_rec is not None and card_rec.usable else None
    )
    subjects = screening_subjects(applicant_inn, card)
    return Snapshot(
        registry=registry_data(card_rec),
        npd=npd_data(records.get(NPD, applicant_inn)),
        bankruptcies=bankruptcy_checks(records, subjects),
        tax=tax_data(
            records.get(TAX_PROFILE, applicant_inn),
            records.get(SME, applicant_inn),
            records.get(BLOCKS, applicant_inn),
        ),
        financials=financials_data(records.get(FINANCIALS, applicant_inn)),
        contracts=contracts_data(records.get(CONTRACTS, applicant_inn)),
        compliance=compliance_data(records.get(COMPLIANCE, applicant_inn), subjects),
        customer=customer_data(
            records.get(CUSTOMER, applicant_inn),
            records.get(LOANS, applicant_inn),
            bki_payments_by_uid(records, bki_subject_list),
        ),
        turnover=turnover_data(records.get(TURNOVER, applicant_inn)),
        statement=statement_data(records.get(STATEMENT, applicant_inn)),
        bki=bki_subject_data(records, bki_subject_list, bki_no_consent),
    )
