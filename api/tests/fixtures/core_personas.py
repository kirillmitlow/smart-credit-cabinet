"""Ручные входы `decide()` для персон и технических сценариев (T-301, T-302, 30-17).

Фикстуры собраны вручную по описанию оракула и НЕ зависят от генератора моков: расхождение с
мок-данными фиксируется вопросом, а не подгонкой. Ряды оборотов плоские, без шума
(`noisePercent: 0`), `APP_TODAY` = 21.10.2026 (30-17, «Общие условия»).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.modules.decisioning import DecisionInput, Policy
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
    Context,
    ContractInfo,
    ContractsData,
    CustomerData,
    FinancialsData,
    FinancialYear,
    Founder,
    Guarantor,
    Mode,
    NpdData,
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
from app.modules.pipeline import load_policy_file

TODAY = date(2026, 10, 21)
POLICY_PATH = Path(__file__).resolve().parents[2] / "policy" / "v1.yaml"

_POLICY: Policy | None = None


def load_policy() -> Policy:
    global _POLICY  # noqa: PLW0603 — кэш на время прогона тестов
    if _POLICY is None:
        _POLICY = load_policy_file(POLICY_PATH)
    return _POLICY


# ---------------------------------------------------------------- строительные блоки


def ok(snapshot_id: str) -> SourceMeta:
    return SourceMeta(SourceStatus.OK, date(2026, 10, 20), snapshot_id)


def not_found(snapshot_id: str) -> SourceMeta:
    return SourceMeta(SourceStatus.NOT_FOUND, date(2026, 10, 20), snapshot_id)


def unavailable() -> SourceMeta:
    return SourceMeta(SourceStatus.UNAVAILABLE)


def month_starts(count: int, last: date = date(2026, 9, 1)) -> list[date]:
    """`count` первых чисел месяцев по возрастанию, последний — `last`."""
    index = last.year * 12 + last.month - 1
    return [date((index - i) // 12, (index - i) % 12 + 1, 1) for i in reversed(range(count))]


def flat_turnover(
    count: int, incoming: int, outgoing: int, payers: int | None = None
) -> tuple[TurnoverMonth, ...]:
    return tuple(TurnoverMonth(m, incoming, outgoing, payers) for m in month_starts(count))


def clean_person() -> BkiReport:
    """Закрытый кредит и карта без долга, история больше двух лет."""
    return BkiReport(
        has_history=True,
        history_months=60,
        active_obligations=1,
        closed_obligations=1,
        obligations=(
            BkiObligation("card-1", "CREDIT_CARD"),
            BkiObligation("loan-1", "LOAN", "CLOSED"),
        ),
    )


def bki(role: SubjectRole, inn: str, rep: BkiReport, sid: str) -> BkiSubject:
    return BkiSubject(role, inn, ok(sid), rep)


def bki_absent(role: SubjectRole, inn: str) -> BkiSubject:
    return BkiSubject(role, inn, not_found(f"bki-{role.value.lower()}"), None)


def compliance(
    *pairs: tuple[str, SubjectRole], listed: SubjectRole | None = None
) -> ComplianceData:
    return ComplianceData(
        ok("compliance"),
        tuple(ComplianceResult(inn, role, aml_listed=(role == listed)) for inn, role in pairs),
    )


def context(mode: Mode = Mode.DECISION) -> Context:
    return Context(app_today=TODAY, mode=mode)


def decision_input(app: Application, snap: Snapshot, mode: Mode = Mode.DECISION) -> DecisionInput:
    return DecisionInput(app, snap, context(mode), load_policy())


# ---------------------------------------------------------------- sokolova


def sokolova() -> DecisionInput:
    inn = "001234567887"
    app = Application("APP-SOKOLOVA", Product.EXPRESS, 500_000, 12)
    card = BkiObligation("card-sok", "CREDIT_CARD", monthly_payment_rub=3_000, balance_rub=60_000)
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.INDIVIDUAL_ENTREPRENEUR,
            inn,
            date(2023, 4, 12),
            "ACTIVE",
            "56.10",
        ),
        bankruptcies=(BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb")),),
        tax=TaxData(ok("tax"), regimes=("USN_INCOME",)),
        compliance=compliance((inn, SubjectRole.COMPANY)),
        customer=CustomerData(ok("abs-customer"), True, date(2023, 5, 2)),
        turnover=TurnoverData(ok("abs-turnover"), flat_turnover(12, 905_000, 795_000, 2)),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=30,
                    active_obligations=1,
                    closed_obligations=1,
                    total_debt_rub=60_000,
                    monthly_payments_rub=3_000,
                    obligations=(card, BkiObligation("loan-sok", "LOAN", "CLOSED")),
                ),
                "bki-company",
            ),
        ),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- snabkontrakt


def snabkontrakt() -> DecisionInput:
    inn, director = "0012345673", "001310000200"
    app = Application(
        "APP-SNAB",
        Product.WORKING_CAPITAL,
        8_000_000,
        12,
        contract_registry_number="1001500002826000127",
        director_name_in_form="Орлов Пётр Игоревич",
    )
    months = month_starts(24)
    turnover = tuple(
        TurnoverMonth(m, 18_000_000 if m < date(2026, 1, 1) else 18_300_000, 0, 12) for m in months
    )
    turnover = tuple(replace(t, outgoing_rub=t.incoming_net_rub - 1_100_000) for t in turnover)
    loans = (
        BkiObligation("snab-loan-1", "LOAN", monthly_payment_rub=350_000, balance_rub=5_000_000),
        BkiObligation("snab-loan-2", "LOAN", monthly_payment_rub=250_000, balance_rub=3_000_000),
    )
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2020, 9, 1),
            "ACTIVE",
            "46.46",
            "Орлов Пётр Игоревич",
            director,
            (Founder("Орлов Пётр Игоревич", director, Decimal(100)),),
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(director, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(ok("tax"), regimes=("OSNO",)),
        financials=FinancialsData(
            ok("gir-bo"),
            (
                FinancialYear(2025, 180_000_000, 13_200_000, 1_200_000),
                FinancialYear(2024, 180_000_000, 12_000_000, 1_100_000),
            ),
        ),
        contracts=ContractsData(
            ok("eis"),
            (ContractInfo("1001500002826000127", 12_000_000, 0, "IN_PROGRESS", date(2027, 1, 15)),),
        ),
        compliance=compliance((inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR)),
        customer=CustomerData(ok("abs-customer"), True, date(2021, 3, 10)),
        turnover=TurnoverData(ok("abs-turnover"), turnover),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=72,
                    active_obligations=2,
                    total_debt_rub=8_000_000,
                    monthly_payments_rub=600_000,
                    obligations=loans,
                ),
                "bki-company",
            ),
            bki(SubjectRole.DIRECTOR, director, clean_person(), "bki-director"),
        ),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- stankoprom


def stankoprom() -> DecisionInput:
    inn, director = "0017654322", "001310000115"
    app = Application(
        "APP-STANKOPROM",
        Product.INVESTMENT,
        15_000_000,
        60,
        collateral=Collateral("покупаемая линия", 25_000_000),
    )
    card = BkiObligation("card-kuz", "CREDIT_CARD", balance_rub=90_000, monthly_payment_rub=4_500)
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2017, 3, 14),
            "ACTIVE",
            "25.62",
            "Кузнецов Игорь Петрович",
            director,
            (Founder("Кузнецов Игорь Петрович", director, Decimal(100)),),
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(director, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(ok("tax"), regimes=("OSNO",)),
        financials=FinancialsData(
            ok("gir-bo"),
            (
                FinancialYear(2025, 420_000_000, 30_700_000, 1_900_000),
                FinancialYear(2024, 388_000_000, 27_400_000, 3_100_000),
            ),
        ),
        compliance=compliance((inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR)),
        customer=CustomerData(not_found("abs-customer"), False),
        turnover=TurnoverData(not_found("abs-turnover")),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=84,
                    closed_obligations=2,
                    obligations=(
                        BkiObligation("sp-loan-1", "LOAN", "CLOSED"),
                        BkiObligation("sp-loan-2", "LOAN", "CLOSED"),
                    ),
                ),
                "bki-company",
            ),
            bki(
                SubjectRole.DIRECTOR,
                director,
                BkiReport(
                    has_history=True,
                    history_months=96,
                    active_obligations=1,
                    closed_obligations=1,
                    total_debt_rub=90_000,
                    monthly_payments_rub=4_500,
                    obligations=(card, BkiObligation("kuz-loan", "LOAN", "CLOSED")),
                ),
                "bki-director",
            ),
        ),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- garipov


def garipov(second_pass: bool = False) -> DecisionInput:
    inn = "001300000555"
    app = Application("APP-GARIPOV", Product.EXPRESS, 1_500_000, 36)
    statement = StatementData()
    if second_pass:
        statement = StatementData(
            ok("statement"), flat_turnover(12, 700_000, 600_000), owner_inn_matches=True
        )
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.INDIVIDUAL_ENTREPRENEUR,
            inn,
            date(2021, 9, 1),
            "ACTIVE",
            "96.02",
        ),
        bankruptcies=(BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb")),),
        tax=TaxData(ok("tax"), regimes=("PSN",)),
        compliance=compliance((inn, SubjectRole.COMPANY)),
        customer=CustomerData(not_found("abs-customer"), False),
        turnover=TurnoverData(not_found("abs-turnover")),
        statement=statement,
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=48,
                    closed_obligations=1,
                    obligations=(BkiObligation("gar-loan", "LOAN", "CLOSED"),),
                ),
                "bki-company",
            ),
        ),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- romashka, vektor, orlov


def romashka() -> DecisionInput:
    inn, director = "0015557771", "001310000436"
    app = Application("APP-ROMASHKA", Product.WORKING_CAPITAL, 3_000_000, 6)
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2019, 10, 1),
            "ACTIVE",
            "46.73",
            "Морозов Олег Викторович",
            director,
            (Founder("Морозов Олег Викторович", director, Decimal(100)),),
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(director, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(
            ok("tax"),
            regimes=("USN_INCOME_MINUS_EXPENSES",),
            tax_debt_rub=1_150_000,
            penalties_rub=42_000,
            offenses_count=1,
        ),
        financials=FinancialsData(
            ok("gir-bo"), (FinancialYear(2025, 95_000_000, 4_000_000, 600_000),)
        ),
        compliance=compliance((inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR)),
        customer=CustomerData(not_found("abs-customer"), False),
        turnover=TurnoverData(not_found("abs-turnover")),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=84,
                    active_obligations=2,
                    closed_obligations=3,
                    total_debt_rub=1_813_000,
                    monthly_payments_rub=318_500,
                    current_overdue_rub=452_000,
                    current_overdue_days=94,
                    max_overdue_days_24m=94,
                    inquiries_30d_excl_own=6,
                    rejected_90d_excl_own=2,
                    obligations=(
                        BkiObligation(
                            "rom-1", "LOAN", monthly_payment_rub=113_000, balance_rub=837_000
                        ),
                        BkiObligation(
                            "rom-2", "LOAN", monthly_payment_rub=205_500, balance_rub=976_000
                        ),
                    ),
                ),
                "bki-company",
            ),
            bki(SubjectRole.DIRECTOR, director, clean_person(), "bki-director"),
        ),
    )
    return decision_input(app, snap)


def vektor() -> DecisionInput:
    inn, director = "0016667772", "001310000777"
    app = Application("APP-VEKTOR", Product.EXPRESS, 2_000_000, 12)
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2022, 10, 1),
            "LIQUIDATING",
            "47.19",
            "Лебедев Антон Сергеевич",
            director,
            (Founder("Лебедев Антон Сергеевич", director, Decimal(100)),),
        ),
        bankruptcies=(BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),),
        tax=TaxData(ok("tax"), regimes=("USN_INCOME",)),
        compliance=compliance((inn, SubjectRole.COMPANY)),
        customer=CustomerData(not_found("abs-customer"), False),
        turnover=TurnoverData(not_found("abs-turnover")),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=40,
                    closed_obligations=1,
                    obligations=(BkiObligation("vek-loan", "LOAN", "CLOSED"),),
                ),
                "bki-company",
            ),
        ),
    )
    return decision_input(app, snap)


def orlov() -> DecisionInput:
    app = Application("APP-ORLOV", Product.EXPRESS, 300_000, 12)
    snap = Snapshot(
        registry=RegistryData(not_found("registry")),
        npd=NpdData(ok("npd"), True),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- zarya


def zarya_turnover() -> tuple[TurnoverMonth, ...]:
    """`650 000 000 / 12 × (1 + 0,6 · sin(2π (m − 6) / 12))`, `m` — номер календарного месяца."""
    out: list[TurnoverMonth] = []
    for month in month_starts(24):
        incoming = round(
            650_000_000 / 12 * (1 + 0.6 * math.sin(2 * math.pi * (month.month - 6) / 12))
        )
        out.append(TurnoverMonth(month, incoming, round(incoming * 0.9), 40))
    return tuple(out)


def zarya() -> DecisionInput:
    inn, director = "0018881113", "001310000888"
    app = Application(
        "APP-ZARYA",
        Product.CREDIT_LINE,
        20_000_000,
        12,
        collateral=Collateral("сельхозтехника", 30_000_000),
    )
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2002, 6, 1),
            "ACTIVE",
            "01.11",
            "Громов Виктор Иванович",
            director,
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(director, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(ok("tax"), regimes=("ESHN",)),
        financials=FinancialsData(
            ok("gir-bo"),
            (
                FinancialYear(2025, 650_000_000, 65_000_000, 4_000_000),
                FinancialYear(2024, 650_000_000, 65_000_000, 4_500_000),
            ),
        ),
        compliance=compliance((inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR)),
        customer=CustomerData(ok("abs-customer"), True, date(2018, 2, 1)),
        turnover=TurnoverData(ok("abs-turnover"), zarya_turnover()),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=240,
                    active_obligations=5,
                    closed_obligations=6,
                    total_debt_rub=40_000_000,
                    monthly_payments_rub=1_500_000,
                    obligations=(
                        BkiObligation(
                            "zar-1", "LOAN", monthly_payment_rub=900_000, balance_rub=25_000_000
                        ),
                        BkiObligation(
                            "zar-2",
                            "CREDIT_LINE",
                            monthly_payment_rub=600_000,
                            balance_rub=15_000_000,
                        ),
                    ),
                ),
                "bki-company",
            ),
            bki(SubjectRole.DIRECTOR, director, clean_person(), "bki-director"),
        ),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- quick-start


def quick_start(with_guarantor: bool = False) -> DecisionInput:
    inn, owner = "0019991114", "001310000999"
    guarantor = Guarantor(owner, True) if with_guarantor else None
    app = Application("APP-QUICK", Product.EXPRESS, 1_000_000, 24, guarantor=guarantor)
    subjects = [
        bki_absent(SubjectRole.COMPANY, inn),
        bki(SubjectRole.DIRECTOR, owner, clean_person(), "bki-director"),
    ]
    if with_guarantor:
        subjects.append(bki(SubjectRole.GUARANTOR, owner, clean_person(), "bki-guarantor"))
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2026, 7, 21),
            "ACTIVE",
            "62.01",
            "Соколов Дмитрий Андреевич",
            owner,
            (Founder("Соколов Дмитрий Андреевич", owner, Decimal(100)),),
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(owner, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(ok("tax"), regimes=("AUSN",)),
        compliance=compliance((inn, SubjectRole.COMPANY), (owner, SubjectRole.DIRECTOR)),
        customer=CustomerData(ok("abs-customer"), True, date(2026, 7, 21)),
        turnover=TurnoverData(ok("abs-turnover"), flat_turnover(3, 700_000, 595_000, 10)),
        bki=tuple(subjects),
    )
    return decision_input(app, snap)


# ---------------------------------------------------------------- T-BASE и технические сценарии


def t_base() -> DecisionInput:
    inn, director = "0020001115", "001310001000"
    app = Application("APP-T-BASE", Product.EXPRESS, 1_000_000, 12)
    snap = Snapshot(
        registry=RegistryData(
            ok("registry"),
            ApplicantKind.LEGAL_ENTITY,
            inn,
            date(2023, 10, 21),
            "ACTIVE",
            "62.01",
            "Миронов Павел Олегович",
            director,
            (Founder("Миронов Павел Олегович", director, Decimal(100)),),
        ),
        bankruptcies=(
            BankruptcyCheck(inn, SubjectRole.COMPANY, None, ok("efrsb-company")),
            BankruptcyCheck(director, SubjectRole.DIRECTOR, None, ok("efrsb-director")),
        ),
        tax=TaxData(ok("tax"), regimes=("USN_INCOME",)),
        financials=FinancialsData(
            ok("gir-bo"),
            (
                FinancialYear(2025, 60_000_000, 9_000_000, 0),
                FinancialYear(2024, 60_000_000, 9_000_000, 0),
            ),
        ),
        compliance=compliance((inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR)),
        customer=CustomerData(ok("abs-customer"), True, date(2024, 10, 21)),
        turnover=TurnoverData(ok("abs-turnover"), flat_turnover(24, 5_000_000, 4_250_000, 12)),
        bki=(
            bki(
                SubjectRole.COMPANY,
                inn,
                BkiReport(
                    has_history=True,
                    history_months=30,
                    closed_obligations=2,
                    obligations=(
                        BkiObligation("tb-loan-1", "LOAN", "CLOSED"),
                        BkiObligation("tb-loan-2", "LOAN", "CLOSED"),
                    ),
                ),
                "bki-company",
            ),
            bki(SubjectRole.DIRECTOR, director, clean_person(), "bki-director"),
        ),
    )
    return decision_input(app, snap)


def with_snapshot(inp: DecisionInput, **changes: object) -> DecisionInput:
    return replace(inp, snapshot=replace(inp.snapshot, **changes))


def with_application(inp: DecisionInput, **changes: object) -> DecisionInput:
    return replace(inp, application=replace(inp.application, **changes))


def company_subject(inp: DecisionInput) -> BkiSubject:
    return next(s for s in inp.snapshot.bki if s.role == SubjectRole.COMPANY)


def with_company_report(inp: DecisionInput, rep: BkiReport) -> DecisionInput:
    subjects = tuple(
        replace(s, report=rep) if s.role == SubjectRole.COMPANY else s for s in inp.snapshot.bki
    )
    return with_snapshot(inp, bki=subjects)


def t_aml() -> DecisionInput:
    base = t_base()
    inn = base.snapshot.registry.inn
    director = base.snapshot.registry.director_inn or ""
    data = compliance(
        (inn, SubjectRole.COMPANY), (director, SubjectRole.DIRECTOR), listed=SubjectRole.DIRECTOR
    )
    return with_snapshot(base, compliance=data)


def t_gambling() -> DecisionInput:
    base = t_base()
    return with_snapshot(base, registry=replace(base.snapshot.registry, okved_main="92.00"))


def t_mass() -> DecisionInput:
    base = t_base()
    return with_snapshot(base, tax=replace(base.snapshot.tax, mass_address=True))


def _overdue_report(days: int, overdue_rub: int) -> BkiReport:
    return BkiReport(
        has_history=True,
        history_months=30,
        active_obligations=1,
        closed_obligations=2,
        total_debt_rub=950_000,
        monthly_payments_rub=77_100,
        current_overdue_rub=overdue_rub,
        current_overdue_days=days,
        max_overdue_days_24m=days,
        obligations=(
            BkiObligation("tb-active", "LOAN", monthly_payment_rub=77_100, balance_rub=950_000),
            BkiObligation("tb-loan-1", "LOAN", "CLOSED"),
            BkiObligation("tb-loan-2", "LOAN", "CLOSED"),
        ),
    )


def t_overdue_45() -> DecisionInput:
    return with_company_report(t_base(), _overdue_report(45, 154_200))


def t_overdue_95() -> DecisionInput:
    return with_company_report(t_base(), _overdue_report(95, 154_200))


def t_bankrupt() -> DecisionInput:
    base = t_base()
    case = BankruptcyCase("А00-45012/2022", "COMPLETED", date(2022, 3, 10), date(2024, 10, 21))
    founder_inn = "001310002000"
    registry = replace(
        base.snapshot.registry,
        founders=(
            *base.snapshot.registry.founders,
            Founder("Беляев Сергей Николаевич", founder_inn, Decimal(40)),
        ),
    )
    checks = (
        *base.snapshot.bankruptcies,
        BankruptcyCheck(
            founder_inn, SubjectRole.FOUNDER, Decimal(40), ok("efrsb-founder"), (case,)
        ),
    )
    founder_report = BkiReport(
        has_history=True,
        history_months=60,
        closed_obligations=2,
        obligations=(
            BkiObligation("bel-1", "LOAN", "CLOSED"),
            BkiObligation("bel-2", "LOAN", "CLOSED"),
        ),
        bankruptcies=(case,),
    )
    return with_snapshot(
        base,
        registry=registry,
        bankruptcies=checks,
        bki=(
            *base.snapshot.bki,
            bki(SubjectRole.FOUNDER, founder_inn, founder_report, "bki-founder"),
        ),
    )


def t_tax_debt() -> DecisionInput:
    base = with_application(
        t_base(), product=Product.WORKING_CAPITAL, amount_rub=3_000_000, term_months=12
    )
    return with_snapshot(base, tax=replace(base.snapshot.tax, tax_debt_rub=750_000))


def t_mismatch() -> DecisionInput:
    base = with_application(
        t_base(), product=Product.WORKING_CAPITAL, amount_rub=3_000_000, term_months=12
    )
    fin = FinancialsData(
        ok("gir-bo"),
        (
            FinancialYear(2025, 36_000_000, 5_400_000, 0),
            FinancialYear(2024, 60_000_000, 9_000_000, 0),
        ),
    )
    return with_snapshot(base, financials=fin)


def t_young_collateral() -> DecisionInput:
    base = t_base()
    inn = base.snapshot.registry.inn
    owner = base.snapshot.registry.director_inn or ""
    app = replace(base.application, collateral=Collateral("оборудование", 1_500_000))
    subjects = (
        bki_absent(SubjectRole.COMPANY, inn),
        bki(SubjectRole.DIRECTOR, owner, clean_person(), "bki-director"),
    )
    snap = replace(
        base.snapshot,
        registry=replace(base.snapshot.registry, registration_date=date(2026, 5, 21)),
        tax=TaxData(ok("tax"), regimes=("AUSN",)),
        financials=FinancialsData(),
        customer=CustomerData(ok("abs-customer"), True, date(2026, 5, 21)),
        turnover=TurnoverData(ok("abs-turnover"), flat_turnover(5, 1_500_000, 1_275_000, 10)),
        bki=subjects,
    )
    return replace(base, application=app, snapshot=snap)


def t_anomaly() -> DecisionInput:
    base = t_base()
    months = month_starts(18)
    turnover = tuple(
        TurnoverMonth(m, 9_000_000 if m >= date(2026, 7, 1) else 5_000_000, 0, 12) for m in months
    )
    turnover = tuple(replace(t, outgoing_rub=t.incoming_net_rub * 85 // 100) for t in turnover)
    snap = replace(
        base.snapshot,
        customer=CustomerData(ok("abs-customer"), True, date(2025, 4, 21)),
        turnover=TurnoverData(ok("abs-turnover"), turnover),
    )
    return replace(base, snapshot=snap)


PERSONAS: dict[str, Callable[[], DecisionInput]] = {
    "sokolova": sokolova,
    "snabkontrakt": snabkontrakt,
    "stankoprom": stankoprom,
    "garipov": lambda: garipov(second_pass=True),
    "garipov-pass1": lambda: garipov(second_pass=False),
    "romashka": romashka,
    "vektor": vektor,
    "orlov": orlov,
    "zarya": zarya,
    "quick-start": quick_start,
    "quick-start-guarantor": lambda: quick_start(with_guarantor=True),
    "t-base": t_base,
    "t-aml": t_aml,
    "t-gambling": t_gambling,
    "t-mass": t_mass,
    "t-overdue-45": t_overdue_45,
    "t-overdue-95": t_overdue_95,
    "t-bankrupt": t_bankrupt,
    "t-tax-debt": t_tax_debt,
    "t-mismatch": t_mismatch,
    "t-young-collateral": t_young_collateral,
    "t-anomaly": t_anomaly,
}
