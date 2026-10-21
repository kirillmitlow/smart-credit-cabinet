"""Встроенные сценарии в общем формате ScenarioSpec (10.5, оракул 30-17).

В T-131 здесь только Соколова; T-132…135 добавят остальных. Стартовое применение — T-128.
Месяцы вычисляются из часов стенда, реквизиты и абсолютные даты остаются постоянными.
"""

from datetime import date
from typing import Any

from app.common.accounts import SETTLEMENT_IP, generate_account
from app.common.clock import last_full_month
from app.common.reldate import add_months
from app.roles.scenarios.identity_people import rng_for
from app.roles.scenarios.schemas import ScenarioSpec

SOKOLOVA_INN = "001234567887"


def builtin_scenarios(today: date, bank_bik: str = "040000999") -> list[ScenarioSpec]:
    """Новые независимые модели на каждый вызов; месяцы — 12 полных перед today.

    bank_bik передаётся из настроек приложения, как в preview. Версия меняется только
    при изменении исходной персоны; смену месяца обработает T-129 отдельно.
    """
    last = last_full_month(today)
    turnover = [
        {
            "month": add_months(last, offset).strftime("%Y-%m"),
            "incomingRub": 905000,
            "incomingNetRub": 905000,
            "outgoingRub": 795000,
            "counterpartiesIn": 2,
            "counterpartiesOut": 25,
        }
        for offset in range(-11, 1)
    ]
    number = generate_account(rng_for("sokolova", "settlement"), bank_bik, SETTLEMENT_IP)
    raw_bank: dict[str, Any] = {
        "customer": {"customerSince": "2023-05-02"},
        "accounts": [
            {
                "number": number,
                "type": "SETTLEMENT",
                "status": "OPEN",
                "openedAt": "2023-05-02",
                "balanceRub": 412300,
            }
        ],
        "turnover": turnover,
    }
    return [
        ScenarioSpec.model_validate(
            {
                "code": "sokolova",
                "title": "ИП Соколова — кофейня, автоматическое одобрение",
                "builtinVersion": 1,
                "preset": "IP_HEALTHY",
                "company": {
                    "form": "IP",
                    "name": "Соколова Анна Сергеевна",
                    "inn": SOKOLOVA_INN,
                    "ogrn": "323000000123450",
                    "registrationDate": "2023-04-12",
                    "okved": "56.10",
                    "regionCode": "16",
                },
                "finance": {
                    "avgMonthlyRevenueRub": 905000,
                    "revenueTrend": "STABLE",
                    "seasonality": "NONE",
                    "noisePercent": 0,
                    "netMarginPercent": 10,
                    "minMonthlySurplusRub": 110000,
                    "taxRegime": "USN_INCOME",
                    "hasStatements": False,
                },
                "bank": {"isCustomer": True, "customerSinceMonths": 41, "balanceRub": 412300},
                "bki": {
                    "owner": {
                        "historyYears": 2.5,
                        "closedLoans": [
                            {
                                "kind": "CONSUMER_LOAN",
                                "amountRub": 300000,
                                "openedAt": "-30M",
                                "closedAt": "-6M",
                            }
                        ],
                        "activeLoans": [
                            {
                                "kind": "CREDIT_CARD",
                                "limitRub": 100000,
                                "balanceRub": 60000,
                                "monthlyPaymentRub": 3000,
                                "openedAt": "-12M",
                            }
                        ],
                        "inquiries30d": 0,
                        "rejectedApplications90d": 0,
                    }
                },
                "application": {
                    "productCode": "EXPRESS",
                    "amountRub": 500000,
                    "termMonths": 12,
                    "collateral": None,
                    "guarantor": None,
                },
                "expectedOutcome": "APPROVED",
                "expectedReasonCodes": [],
                "users": [
                    {
                        "login": "sokolova",
                        "role": "DIRECTOR",
                        "personRef": "self",
                        "inn": SOKOLOVA_INN,
                        "fullName": "Соколова Анна Сергеевна",
                    }
                ],
                "raw": {"bankCore": raw_bank},
            }
        )
    ]
