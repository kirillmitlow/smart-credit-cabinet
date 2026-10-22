"""Образцы ответов моков (спецификация моков, разделы 4–7) для unit-тестов адаптеров.

Это копии JSON из контракта, а не импорт кода моков: адаптеры связаны с мокам только форматом.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def meta(source: str, requestId: str = "req_TEST") -> dict[str, Any]:  # noqa: N803 — как в JSON
    return {
        "source": source,
        "simulated": True,
        "requestId": requestId,
        "retrievedAt": "2026-10-21T09:12:03Z",
        "dataActualAt": "2026-10-20",
    }


COMPANY_LLC: dict[str, Any] = {
    "meta": meta("EGRUL"),
    "type": "LEGAL_ENTITY",
    "inn": "0017654322",
    "kpp": "001701001",
    "ogrn": "1170000004569",
    "registrationDate": "2017-03-14",
    "fullName": "ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ «СТАНКОПРОМ»",
    "shortName": "ООО «СтанкоПром»",
    "legalForm": {"okopf": "12300", "name": "Общество с ограниченной ответственностью"},
    "status": {"code": "LIQUIDATING", "name": "Ликвидируется", "since": "2026-09-01"},
    "pendingExclusion": {
        "decisionDate": "2026-09-10",
        "grn": "2260000111226",
        "objectionsDeadline": "2026-12-10",
    },
    "address": {
        "regionCode": "66",
        "regionName": "Свердловская область",
        "full": "620000, Свердловская обл., г. Екатеринбург, ул. Заводская, д. 1",
        "unreliable": {"since": "2026-08-01", "grn": "2260000987651", "reason": "Проверка"},
    },
    "authorizedCapitalRub": 500000,
    "director": {
        "fullName": "Кузнецов Игорь Петрович",
        "inn": "001310000115",
        "position": "Генеральный директор",
        "since": "2017-03-14",
        "unreliable": None,
    },
    "founders": [
        {
            "type": "PERSON",
            "fullName": "Кузнецов Игорь Петрович",
            "inn": "001310000115",
            "sharePercent": 100,
            "shareNominalRub": 500000,
            "unreliable": None,
        }
    ],
    "okvedMain": {"code": "25.62", "name": "Обработка металлических изделий механическая"},
    "okvedAdditional": [{"code": "28.41", "name": "Производство оборудования"}],
    "taxAuthority": {"code": "0017", "name": "ИФНС № 17"},
    "lastRecord": {"grn": "2230000123450", "date": "2023-06-01"},
}

COMPANY_IP: dict[str, Any] = {
    "meta": meta("EGRIP"),
    "type": "INDIVIDUAL_ENTREPRENEUR",
    "inn": "001234567887",
    "ogrnip": "323000000123450",
    "registrationDate": "2023-04-12",
    "person": {"lastName": "Соколова", "firstName": "Анна", "fullName": "Соколова Анна Сергеевна"},
    "status": {"code": "ACTIVE", "name": "Действующее", "since": "2023-04-12"},
    "region": {"code": "16", "name": "Республика Татарстан"},
    "okvedMain": {"code": "56.10", "name": "Рестораны"},
    "okvedAdditional": [],
    "taxAuthority": {"code": "0012", "name": "ИФНС № 12"},
}

PERSON_ROLES: dict[str, Any] = {
    "meta": meta("EGRUL"),
    "personInn": "001310000115",
    "roles": [
        {
            "role": "DIRECTOR",
            "entityInn": "0017654322",
            "entityName": "ООО «СтанкоПром»",
            "entityStatus": "ACTIVE",
            "since": "2017-03-14",
            "sharePercent": None,
        },
        {
            "role": "FOUNDER",
            "entityInn": "0017654322",
            "entityName": "ООО «СтанкоПром»",
            "entityStatus": "ACTIVE",
            "since": "2017-03-14",
            "sharePercent": 100,
        },
    ],
}

BANKRUPTCIES: dict[str, Any] = {
    "meta": meta("FEDRESURS"),
    "inn": "001310000820",
    "bankruptcies": [
        {
            "caseNumber": "А00-45012/2022",
            "subjectType": "PERSON",
            "stage": "COMPLETED",
            "startedAt": "2022-03-10",
            "completedAt": "2024-10-15",
        }
    ],
}

TAX_PROFILE: dict[str, Any] = {
    "meta": meta("FNS_TRANSPARENT_BUSINESS"),
    "inn": "0015557771",
    "taxRegimes": [{"code": "USN_INCOME_MINUS_EXPENSES", "year": 2025}],
    "avgHeadcount": {"value": 12, "year": 2025},
    "taxesPaid": [{"year": 2025, "totalRub": 3410000}, {"year": 2024, "totalRub": 3120000}],
    "debts": {"asOf": "2026-10-01", "taxDebtRub": 1150000, "penaltiesRub": 42000, "finesRub": 0},
    "incomeExpenses": {"year": 2025, "incomeRub": 95000000, "expensesRub": 91000000},
    "taxOffenses": {"year": 2025, "count": 1, "finesRub": 5000},
    "riskFlags": {
        "massAddress": False,
        "massDirector": False,
        "massFounder": False,
        "disqualifiedManagement": False,
        "noReportsOverYear": False,
    },
}

FINANCIALS: dict[str, Any] = {
    "meta": meta("FNS_GIR_BO"),
    "inn": "0017654322",
    "year": 2025,
    "availableYears": [2025, 2024],
    "formType": "FULL",
    "submittedAt": "2026-03-28",
    "lines": {
        "1600": {"current": 323000000, "previous": 299000000},
        "2110": {"current": 420000000, "previous": 388000000},
        "2330": {"current": 1900000, "previous": 3100000},
        "2400": {"current": 30700000, "previous": 27400000},
    },
    "summary": {
        "revenueRub": 420000000,
        "salesProfitRub": 41500000,
        "interestPayableRub": 1900000,
        "netProfitRub": 30700000,
        "totalAssetsRub": 323000000,
        "equityRub": 196000000,
        "longTermLiabilitiesRub": 22000000,
        "shortTermLiabilitiesRub": 105000000,
    },
}

SME: dict[str, Any] = {
    "meta": meta("FNS_RMSP"),
    "inn": "0012221117",
    "inRegistry": True,
    "category": "MICRO",
    "includedAt": "2026-08-10",
    "isNewlyCreated": True,
    "isSocialEnterprise": False,
}

NPD_TRUE: dict[str, Any] = {"status": True, "message": "001211122200 является плательщиком НПД"}

BLOCKS: dict[str, Any] = {
    "meta": meta("FNS_BLOCKS"),
    "inn": "0015557771",
    "checkedAt": "2026-10-20T09:12:03Z",
    "decisions": [
        {
            "number": "4512",
            "date": "2026-09-15",
            "taxAuthorityCode": "0015",
            "bik": "040000111",
            "reason": "TAX_DEBT_COLLECTION",
        }
    ],
}

CONTRACTS: dict[str, Any] = {
    "meta": meta("EIS"),
    "supplierInn": "0012345673",
    "contracts": [
        {
            "registryNumber": "1001500002826000127",
            "customer": {"name": "ГБУЗ «Городская больница № 5»", "inn": "0015000028"},
            "subject": "Поставка медицинских изделий",
            "priceRub": 12000000,
            "concludedAt": "2026-09-01",
            "executionDeadline": "2026-12-15",
            "paymentDeadline": "2027-01-15",
            "status": "IN_PROGRESS",
            "paidRub": 0,
        }
    ],
}

CUSTOMER: dict[str, Any] = {
    "meta": meta("BANK_CORE"),
    "customerId": "cus_000017",
    "inn": "001234567887",
    "type": "INDIVIDUAL_ENTREPRENEUR",
    "name": "ИП Соколова Анна Сергеевна",
    "customerSince": "2023-05-02",
    "accounts": [
        {
            "number": "40802810800000001234",
            "type": "SETTLEMENT",
            "currency": "RUB",
            "status": "OPEN",
            "openedAt": "2023-05-02",
            "balanceRub": 412300,
        }
    ],
}

TURNOVER: dict[str, Any] = {
    "meta": meta("BANK_CORE"),
    "inn": "001234567887",
    "accountNumbers": ["40802810800000001234"],
    "months": [
        {
            "month": "2026-08",
            "incomingRub": 911800,
            "incomingNetRub": 905000,
            "outgoingRub": 795000,
            "counterpartiesIn": 2,
            "counterpartiesOut": 25,
        },
        {
            "month": "2026-09",
            "incomingRub": 911800,
            "incomingNetRub": 905000,
            "outgoingRub": 795000,
            "counterpartiesIn": 2,
            "counterpartiesOut": 23,
        },
    ],
}

LOANS: dict[str, Any] = {
    "meta": meta("BANK_CORE"),
    "inn": "001234567887",
    "loans": [
        {
            "loanId": "loan_000041",
            "applicationRef": "APP-2026-000123",
            "contractNumber": "КД-2026-000123",
            "contractUid": "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4",
            "productCode": "EXPRESS",
            "kind": "LOAN",
            "amountRub": 500000,
            "limitRub": None,
            "outstandingRub": 500000,
            "termMonths": 12,
            "ratePercent": 24.0,
            "repaymentType": "ANNUITY",
            "loanAccount": "45406810000000000041",
            "settlementAccount": "40802810800000001234",
            "status": "ACTIVE",
            "disbursedAt": "2026-10-20",
        }
    ],
}

SCREENING: dict[str, Any] = {
    "meta": meta("COMPLIANCE"),
    "screeningId": "scr_01JAKA9",
    "overall": "HIT",
    "results": [
        {
            "inn": "0017654322",
            "role": "COMPANY",
            "amlList": {"listed": False, "listName": None},
            "zsk": {"riskLevel": "GREEN", "assessedAt": "2026-10-01"},
            "internalStopList": {"listed": False, "reason": None},
        },
        {
            "inn": "001310000115",
            "role": "DIRECTOR",
            "amlList": {"listed": True, "listName": "ROSFINMONITORING_TERRORISM_EXTREMISM"},
            "zsk": None,
            "internalStopList": {"listed": False, "reason": None},
        },
    ],
}

REPORT: dict[str, Any] = {
    "meta": meta("CREDIT_BUREAU"),
    "reportId": "rep_01JAK9ZQ1R",
    "generatedAt": "2026-10-21T09:12:05Z",
    "matchStatus": "MATCHED",
    "subject": {
        "type": "LEGAL_ENTITY",
        "inn": "0015557771",
        "ogrn": "1190000007890",
        "name": "ООО «Ромашка»",
    },
    "hasHistory": True,
    "summary": {
        "activeObligations": 2,
        "closedObligations": 3,
        "totalDebtRub": 1813000,
        "monthlyPaymentsRub": 318500,
        "contingentLiabilitiesRub": 0,
        "currentOverdueRub": 452000,
        "currentOverdueDays": 94,
        "maxOverdueDays24m": 94,
        "restructurings24m": 0,
        "inquiries30d": 7,
        "inquiries30dExcludingOwn": 6,
        "rejectedApplications90d": 2,
        "rejectedApplications90dExcludingOwn": 2,
        "historyLengthMonths": 84,
    },
    "obligations": [
        {
            "uid": "6f1c2a8e-4b7d-4f0a-9c3e-2d5b8a1f7e60-4",
            "kind": "LOAN",
            "role": "BORROWER",
            "openedAt": "2024-02-18",
            "plannedCloseAt": "2027-02-18",
            "closedAt": None,
            "amountRub": 3000000,
            "limitRub": None,
            "balanceRub": 837000,
            "monthlyPaymentRub": 113000,
            "overdueRub": 452000,
            "overdueDays": 94,
            "status": "ACTIVE",
            "secured": False,
            "paymentHistory": [
                {"month": "2026-08", "status": "D30_59"},
                {"month": "2026-09", "status": "D60_89"},
            ],
        }
    ],
    "inquiries": [
        {"date": "2026-10-21", "userType": "BANK", "purpose": "LOAN_APPLICATION", "isOwn": True},
        {"date": "2026-10-14", "userType": "BANK", "purpose": "LOAN_APPLICATION", "isOwn": False},
    ],
    "applications": [
        {
            "date": "2026-10-14",
            "kind": "LOAN",
            "amountRub": 2000000,
            "decision": "REJECTED",
            "decisionDate": "2026-10-15",
            "isOwn": False,
        }
    ],
    "bankruptcies": [
        {
            "caseNumber": "А00-45012/2022",
            "stage": "COMPLETED",
            "startedAt": "2022-03-10",
            "completedAt": "2024-10-15",
        }
    ],
    "bureauScore": {"value": 512, "scaleMin": 300, "scaleMax": 850, "model": "SIM-B2B-1"},
}

RECEIPT: dict[str, Any] = {
    "meta": meta("CREDIT_BUREAU"),
    "submissionId": "sub_3372C171510F",
    "status": "ACCEPTED",
}


def problem(code: str, status: int) -> dict[str, Any]:
    return {
        "type": f"https://mocks.smart-credit.local/problems/{code.lower()}",
        "title": "Problem",
        "status": status,
        "code": code,
        "requestId": "req_PROBLEM",
    }


def copy(payload: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(payload)
