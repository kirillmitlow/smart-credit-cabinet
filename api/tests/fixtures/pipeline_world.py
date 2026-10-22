"""Мир заглушек для тестов конвейера: ответы источников «как у мока» и подставные адаптеры (T-272).

Данные Соколовой и Ромашки собраны по описанию оракула 30-17 (как `core_personas.py`), но в виде
JSON мока: он проходит тот же разбор, что и живой ответ (`map_*` адаптеров), поэтому тест проверяет
всю цепочку «ответ источника → снимок → вход ядра → решение». Сеть не используется.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.integrations import (
    BkiConsent,
    BureauSubject,
    Integrations,
    Ok,
    Reason,
    Result,
    ScreeningSubject,
    SnapshotMeta,
    SourceUnavailable,
    System,
)
from app.modules.integrations.bank_core import map_customer, map_loans, map_screening, map_turnover
from app.modules.integrations.credit_bureau import map_report
from app.modules.integrations.registry import map_bankruptcies, map_company
from app.modules.integrations.tax import (
    map_blocks,
    map_contracts,
    map_financials,
    map_sme,
    map_tax_profile,
)
from app.shared import clock

DATA_DATE = date(2026, 10, 20)


def months(count: int, last: tuple[int, int] = (2026, 9)) -> list[str]:
    index = last[0] * 12 + last[1] - 1
    return [f"{(index - i) // 12}-{(index - i) % 12 + 1:02d}" for i in reversed(range(count))]


def flat_turnover(
    inn: str, count: int, incoming: int, outgoing: int, payers: int
) -> dict[str, Any]:
    return {
        "inn": inn,
        "accountNumbers": ["40802810800000001234"],
        "months": [
            {
                "month": m,
                "incomingRub": incoming,
                "incomingNetRub": incoming,
                "outgoingRub": outgoing,
                "counterpartiesIn": payers,
                "counterpartiesOut": 20,
            }
            for m in months(count)
        ],
    }


def report(
    inn: str,
    subject_type: str,
    *,
    history_months: int = 60,
    active: int = 0,
    closed: int = 0,
    debt: int = 0,
    payments: int = 0,
    overdue_rub: int = 0,
    overdue_days: int = 0,
    inquiries: int = 0,
    rejected: int = 0,
    obligations: list[dict[str, Any]] | None = None,
    match: str = "MATCHED",
) -> dict[str, Any]:
    return {
        "reportId": f"rep_{inn}",
        "generatedAt": "2026-10-21T09:12:05Z",
        "matchStatus": match,
        "subject": {"type": subject_type, "inn": inn},
        "hasHistory": match == "MATCHED",
        "summary": {
            "activeObligations": active,
            "closedObligations": closed,
            "totalDebtRub": debt,
            "monthlyPaymentsRub": payments,
            "contingentLiabilitiesRub": 0,
            "currentOverdueRub": overdue_rub,
            "currentOverdueDays": overdue_days,
            "maxOverdueDays24m": overdue_days,
            "restructurings24m": 0,
            "inquiries30d": inquiries,
            "inquiries30dExcludingOwn": inquiries,
            "rejectedApplications90d": rejected,
            "rejectedApplications90dExcludingOwn": rejected,
            "historyLengthMonths": history_months,
        },
        "obligations": obligations or [],
        "inquiries": [],
        "applications": [],
        "bankruptcies": [],
    }


def obligation(
    uid: str, kind: str, status: str = "ACTIVE", payment: int = 0, balance: int = 0
) -> dict[str, Any]:
    return {
        "uid": uid,
        "kind": kind,
        "role": "BORROWER",
        "status": status,
        "openedAt": "2024-01-10",
        "balanceRub": balance,
        "monthlyPaymentRub": payment,
    }


def screening(*pairs: tuple[str, str], listed: str | None = None) -> dict[str, Any]:
    return {
        "screeningId": "scr_test",
        "overall": "CLEAR",
        "results": [
            {
                "inn": inn,
                "role": role,
                "amlList": {"listed": role == listed, "listName": None},
                "zsk": None,
                "internalStopList": {"listed": False, "reason": None},
            }
            for inn, role in pairs
        ],
    }


def tax_profile(
    inn: str, regime: str, debt: int = 0, penalties: int = 0, offenses: int = 0
) -> dict[str, Any]:
    return {
        "inn": inn,
        "taxRegimes": [{"code": regime, "year": 2025}],
        "debts": {
            "asOf": "2026-10-01",
            "taxDebtRub": debt,
            "penaltiesRub": penalties,
            "finesRub": 0,
        },
        "taxOffenses": {"year": 2025, "count": offenses, "finesRub": 0} if offenses else None,
        "riskFlags": {
            "massAddress": False,
            "massDirector": False,
            "massFounder": False,
            "disqualifiedManagement": False,
            "noReportsOverYear": False,
        },
    }


def financials(inn: str, revenue: int, profit: int, interest: int) -> dict[str, Any]:
    return {
        "inn": inn,
        "year": 2025,
        "availableYears": [2025],
        "formType": "FULL",
        "lines": {
            "2110": {"current": revenue, "previous": None},
            "2330": {"current": interest, "previous": None},
            "2400": {"current": profit, "previous": None},
        },
        "summary": {
            "revenueRub": revenue,
            "salesProfitRub": profit,
            "interestPayableRub": interest,
            "netProfitRub": profit,
            "totalAssetsRub": 0,
            "equityRub": 0,
            "longTermLiabilitiesRub": 0,
            "shortTermLiabilitiesRub": 0,
        },
    }


@dataclass
class World:
    """Что отвечают источники и сколько раз их спросили."""

    registry: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    bankruptcies: dict[str, dict[str, Any]] = field(default_factory=dict)
    tax: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    financials: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    customer: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    turnover: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    loans: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    screening: dict[str, dict[str, Any]] = field(default_factory=dict)
    bki: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Ресурсы, которые «не отвечают»: "registry:company", "credit_bureau:report"…
    down: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def count(self, resource: str, inn: str | None = None) -> int:
        return sum(1 for r, i in self.calls if r == resource and (inn is None or i == inn))


def _meta(system: System) -> SnapshotMeta:
    return SnapshotMeta(
        system=system,
        source="TEST",
        request_id="req_test",
        retrieved_at=clock.system_now(),
        data_actual_at=DATA_DATE,
    )


class _Base:
    system: System

    def __init__(self, world: World) -> None:
        self.world = world

    def _answer(
        self, resource: str, inn: str, payload: dict[str, Any] | None, parse: Any
    ) -> Result[Any]:
        self.world.calls.append((resource, inn))
        if resource in self.world.down:
            return SourceUnavailable(self.system, Reason.TIMEOUT, attempts=3, resource=resource)
        if payload is None:
            return Ok(None, _meta(self.system), raw=None)
        return Ok(parse(payload), _meta(self.system), raw=payload)


class FakeRegistry(_Base):
    system = System.REGISTRY

    def get_company(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        data = self.world.registry.get(inn)
        return self._answer("registry:company", inn, data, map_company)

    def get_bankruptcies(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        data = self.world.bankruptcies.get(inn, {"bankruptcies": []})
        return self._answer("registry:bankruptcies", inn, data, map_bankruptcies)


class FakeTax(_Base):
    system = System.TAX

    def get_tax_profile(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        return self._answer("tax:profile", inn, self.world.tax.get(inn), map_tax_profile)

    def get_financials(
        self, inn: str, year: int | None = None, *, application_id: Any = None
    ) -> Result[Any]:
        return self._answer("tax:financials", inn, self.world.financials.get(inn), map_financials)

    def get_sme_status(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        return self._answer("tax:sme", inn, {"inn": inn, "inRegistry": False}, map_sme)

    def get_account_blocks(
        self, inn: str, bik: str | None = None, *, application_id: Any = None
    ) -> Result[Any]:
        return self._answer("tax:blocks", inn, {"decisions": []}, map_blocks)

    def get_gov_contracts(
        self, inn: str, status: str | None = None, *, application_id: Any = None
    ) -> Result[Any]:
        return self._answer("tax:contracts", inn, {"contracts": []}, map_contracts)

    def get_self_employed_status(
        self, inn: str, on: date | None = None, *, application_id: Any = None
    ) -> Result[Any]:
        raise AssertionError("НПД в этих сценариях не нужен")


class FakeBankCore(_Base):
    system = System.BANK_CORE

    def get_customer(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        return self._answer("bank_core:customer", inn, self.world.customer.get(inn), map_customer)

    def get_turnover(
        self, inn: str, months: int = 12, *, application_id: Any = None
    ) -> Result[Any]:
        return self._answer("bank_core:turnover", inn, self.world.turnover.get(inn), map_turnover)

    def get_loans(self, inn: str, *, application_id: Any = None) -> Result[Any]:
        return self._answer("bank_core:loans", inn, self.world.loans.get(inn), map_loans)

    def screen(
        self, subjects: list[ScreeningSubject], *, application_id: Any = None
    ) -> Result[Any]:
        inn = subjects[0].inn
        return self._answer("bank_core:compliance", inn, self.world.screening[inn], map_screening)


class FakeBureau(_Base):
    system = System.CREDIT_BUREAU

    def request_report(
        self,
        consent: BkiConsent,
        subject: BureauSubject,
        application_ref: str,
        *,
        purpose: str = "LOAN_APPLICATION",
        application_id: Any = None,
    ) -> Result[Any]:
        return self._answer(
            "credit_bureau:report", subject.inn, self.world.bki[subject.inn], map_report
        )


def build_integrations(world: World) -> Integrations:
    return Integrations(
        registry=FakeRegistry(world),  # type: ignore[arg-type]
        tax=FakeTax(world),  # type: ignore[arg-type]
        bank_core=FakeBankCore(world),  # type: ignore[arg-type]
        credit_bureau=FakeBureau(world),  # type: ignore[arg-type]
        client=None,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- персоны (30-17)

SOKOLOVA_INN = "001234567887"
ROMASHKA_INN = "0015557771"
ROMASHKA_DIRECTOR = "001310000436"


def sokolova_world() -> World:
    inn = SOKOLOVA_INN
    return World(
        registry={
            inn: {
                "type": "INDIVIDUAL_ENTREPRENEUR",
                "inn": inn,
                "ogrnip": "323000000123450",
                "registrationDate": "2023-04-12",
                "person": {"fullName": "Соколова Анна Сергеевна"},
                "status": {"code": "ACTIVE", "since": "2023-04-12"},
                "okvedMain": {"code": "56.10"},
            }
        },
        tax={inn: tax_profile(inn, "USN_INCOME")},
        customer={
            inn: {
                "customerId": "cus_000017",
                "inn": inn,
                "type": "INDIVIDUAL_ENTREPRENEUR",
                "name": "ИП Соколова Анна Сергеевна",
                "customerSince": "2023-05-02",
                "accounts": [],
            }
        },
        turnover={inn: flat_turnover(inn, 12, 905_000, 795_000, 2)},
        loans={inn: {"loans": []}},
        screening={inn: screening((inn, "IE"))},
        bki={
            inn: report(
                inn,
                "PERSON",
                history_months=30,
                active=1,
                closed=1,
                debt=60_000,
                payments=3_000,
                obligations=[
                    obligation("card-sok", "CREDIT_CARD", payment=3_000, balance=60_000),
                    obligation("loan-sok", "LOAN", "CLOSED"),
                ],
            )
        },
    )


def romashka_world() -> World:
    inn, director = ROMASHKA_INN, ROMASHKA_DIRECTOR
    return World(
        registry={
            inn: {
                "type": "LEGAL_ENTITY",
                "inn": inn,
                "ogrn": "1190000007890",
                "shortName": "ООО «Ромашка»",
                "registrationDate": "2019-10-01",
                "status": {"code": "ACTIVE"},
                "okvedMain": {"code": "46.73"},
                "director": {"fullName": "Морозов Олег Викторович", "inn": director},
                "founders": [
                    {
                        "type": "PERSON",
                        "fullName": "Морозов Олег Викторович",
                        "inn": director,
                        "sharePercent": 100,
                    }
                ],
            }
        },
        tax={
            inn: tax_profile(
                inn, "USN_INCOME_MINUS_EXPENSES", debt=1_150_000, penalties=42_000, offenses=1
            )
        },
        financials={inn: financials(inn, 95_000_000, 4_000_000, 600_000)},
        customer={inn: None},
        turnover={inn: None},
        loans={inn: None},
        screening={inn: screening((inn, "COMPANY"), (director, "DIRECTOR"))},
        bki={
            inn: report(
                inn,
                "LEGAL_ENTITY",
                history_months=84,
                active=2,
                closed=3,
                debt=1_813_000,
                payments=318_500,
                overdue_rub=452_000,
                overdue_days=94,
                inquiries=6,
                rejected=2,
                obligations=[
                    obligation("rom-1", "LOAN", payment=113_000, balance=837_000),
                    obligation("rom-2", "LOAN", payment=205_500, balance=976_000),
                ],
            ),
            director: report(
                director,
                "PERSON",
                active=1,
                closed=1,
                obligations=[
                    obligation("card-1", "CREDIT_CARD"),
                    obligation("loan-1", "LOAN", "CLOSED"),
                ],
            ),
        },
    )
