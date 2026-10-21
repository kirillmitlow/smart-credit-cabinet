"""Пресеты сценариев (10.2): значения по умолчанию, поверх которых ложатся параметры сценария.

Значения — в терминах ScenarioSpec (camelCase), чтобы их можно было показать в GET /presets
и склеить с телом запроса тем же JSON Merge Patch.
"""

from __future__ import annotations

from typing import Any

from app.roles.scenarios.schemas import Preset

_CLEAN_PERSON_HISTORY: dict[str, Any] = {
    "historyYears": 3,
    "closedLoans": [
        {"kind": "CONSUMER_LOAN", "amountRub": 300000, "openedAt": "-3y", "closedAt": "-1y"},
    ],
    "activeLoans": [{"kind": "CREDIT_CARD", "limitRub": 100000, "balanceRub": 0}],
}

PRESETS: dict[Preset, tuple[str, dict[str, Any]]] = {
    Preset.IP_HEALTHY: (
        "ИП 3 года, УСН 6%, выручка 800 тыс./мес, чистая личная история, клиент банка",
        {
            "company": {"form": "IP", "ageMonths": 36, "okved": "47.19"},
            "finance": {
                "avgMonthlyRevenueRub": 800000,
                "taxRegime": "USN_INCOME",
                "netMarginPercent": 12,
            },
            "bki": {"owner": _CLEAN_PERSON_HISTORY},
            "bank": {"isCustomer": True, "customerSinceMonths": 24, "balanceRub": 300000},
        },
    ),
    Preset.LLC_HEALTHY: (
        "ООО 5 лет, ОСНО, выручка 10 млн/мес, отчётность, 1 кредит без просрочек, не клиент",
        {
            "company": {"form": "LLC", "ageMonths": 60, "okved": "46.90"},
            "finance": {
                "avgMonthlyRevenueRub": 10000000,
                "taxRegime": "OSNO",
                "hasStatements": True,
                "netMarginPercent": 8,
            },
            "bki": {
                "company": {
                    "historyYears": 4,
                    "activeLoans": [
                        {"kind": "LOAN", "amountRub": 12000000, "termMonths": 36, "ratePercent": 18}
                    ],
                },
                "director": _CLEAN_PERSON_HISTORY,
                "owner": _CLEAN_PERSON_HISTORY,
            },
            "bank": {"isCustomer": False},
        },
    ),
    Preset.LLC_HIGH_DEBT_LOAD: (
        "Как LLC_HEALTHY, но платежи по кредитам 70% денежного потока",
        {
            "company": {"form": "LLC", "ageMonths": 60, "okved": "46.90"},
            "finance": {
                "avgMonthlyRevenueRub": 10000000,
                "taxRegime": "OSNO",
                "hasStatements": True,
                "netMarginPercent": 8,
            },
            # Поток ≈ 10 млн × 8% = 800 тыс./мес; 70% от него — 560 тыс. платежей
            "bki": {
                "company": {"historyYears": 4, "monthlyPaymentsRub": 560000},
                "director": _CLEAN_PERSON_HISTORY,
                "owner": _CLEAN_PERSON_HISTORY,
            },
            "bank": {"isCustomer": False},
        },
    ),
    Preset.STARTUP: (
        "ООО 3 месяца, АУСН, без истории, без отчётности",
        {
            "company": {"form": "LLC", "ageMonths": 3, "okved": "62.01"},
            "finance": {
                "avgMonthlyRevenueRub": 500000,
                "taxRegime": "AUSN",
                "hasStatements": False,
            },
            "bki": {"company": {"historyYears": 0}, "owner": _CLEAN_PERSON_HISTORY},
            "bank": {"isCustomer": True, "customerSinceMonths": 3},
        },
    ),
    Preset.SELF_EMPLOYED: (
        "Самозанятый: только статус НПД",
        {
            "company": {"form": "SELF_EMPLOYED"},
            "finance": {"taxRegime": "NPD", "hasStatements": False},
            "bank": {"isCustomer": False},
        },
    ),
    Preset.PROBLEM_DEBTOR: (
        "ООО с просрочкой 90+ и налоговым долгом",
        {
            "company": {"form": "LLC", "ageMonths": 48, "okved": "46.73"},
            "finance": {"avgMonthlyRevenueRub": 6000000, "taxRegime": "USN_INCOME_MINUS_EXPENSES"},
            "tax": {"taxDebtRub": 900000},
            "bki": {
                "company": {
                    "historyYears": 3,
                    "activeLoans": [
                        {"kind": "LOAN", "amountRub": 3000000, "termMonths": 36, "ratePercent": 20}
                    ],
                    "currentOverdueDays": 94,
                },
                "director": _CLEAN_PERSON_HISTORY,
            },
            "bank": {"isCustomer": False},
        },
    ),
}
