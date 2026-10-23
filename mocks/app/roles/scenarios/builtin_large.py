"""Встроенные «крупные» персоны T-133: snabkontrakt, stankoprom и zarya.

Формат — тот же `ScenarioSpec`, что у Соколовой (`builtin.py`, T-131) и простых персон
(`builtin_simple.py`, T-132/T-134). Точные входы взяты из оракула 30-17 и ручных входов ядра
`api/tests/fixtures/core_personas.py`. Что оракул не задаёт, названо допущением в комментарии
рядом с числом. Реквизиты и абсолютные даты постоянны. Кредиты открыты относительными датами
(`-26M`), поэтому платёж и остаток не уезжают при сдвиге «сегодня».
"""

from __future__ import annotations

from typing import Any

from app.roles.scenarios.builtin_simple import clean_person
from app.roles.scenarios.schemas import ScenarioSpec

SNABKONTRAKT_INN = "0012345673"
STANKOPROM_INN = "0017654322"
ZARYA_INN = "0014443330"

# Личные ИНН региона 00 с верной контрольной суммой. Кузнецов и Белова — из примера 10.5.
ORLOV_INN = "001310000362"  # директор и владелец «СнабКонтракта»
KUZNETSOV_INN = "001310000115"  # директор и владелец «СтанкоПрома»
BELOVA_INN = "001310000299"  # бухгалтер «СтанкоПрома» с доверенностью
GROMOV_INN = "001310000901"  # директор АО «Заря»


def _statement(year: int, form: str, lines: dict[str, int]) -> dict[str, Any]:
    """Одна запись отчётности целиком: `raw` заменяет год полностью (10 строк, баланс сходится)."""
    return {"year": year, "formType": form, "lines": lines}


def _snabkontrakt() -> ScenarioSpec:
    """ООО-поставщик медтоваров: хороший клиент, но запрошенный платёж не по силам (30-17)."""
    return ScenarioSpec.model_validate(
        {
            "code": "snabkontrakt",
            "title": "ООО «СнабКонтракт» — хороший клиент, встречное предложение",
            "builtinVersion": 1,
            "preset": "LLC_HEALTHY",
            "company": {
                "form": "LLC",
                "name": "СнабКонтракт",
                "inn": SNABKONTRAKT_INN,
                # «6 лет» (30-17); дата из ручных входов ядра, абсолютная
                "registrationDate": "2020-09-01",
                "okved": "46.46",
                "regionCode": "77",
            },
            "people": {
                "director": {
                    "ref": "orlov",
                    "inn": ORLOV_INN,
                    "fullName": "Орлов Пётр Игоревич",
                    "birthDate": "1978-11-03",
                    "sharePercent": 100,
                }
            },
            "finance": {
                # Выручка без НДС ровно 15 млн в месяц (180 млн в год). Поступления с НДС по
                # дате месяца: 18 000 000 до 12.2025 (20%) и 18 300 000 с 01.2026 (22%), ряд без
                # шума. Остаток месяца ровно 1 100 000: маржа 5% даёт 750 000, берётся большее.
                "avgMonthlyRevenueRub": 15000000,
                "noisePercent": 0,
                "netMarginPercent": 5,
                "minMonthlySurplusRub": 1100000,
                "taxRegime": "OSNO",
                "hasStatements": True,
                # Допущение: 40 человек — малое предприятие (выручка выше порога микро)
                "headcount": 40,
            },
            # Клиент с марта 2021 (≥ 36 мес., 30-17). Остаток на счёте оракул не задаёт:
            # допущение 2 400 000.
            "bank": {"isCustomer": True, "customerSinceMonths": 67, "balanceRub": 2400000},
            "bki": {
                "company": {
                    # Два активных кредита, без закрытых. Сумма платежей 600 000 и остатков
                    # 8 000 000 на любую дату (даты относительные), без просрочек. Разбивка —
                    # допущение; суммы и сроки подобраны под оракул, ставка выводится из платежа.
                    "historyYears": None,
                    "activeLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 8008600,
                            "termMonths": 44,
                            "ratePercent": 18,
                            "openedAt": "-26M",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 10124900,
                            "termMonths": 39,
                            "ratePercent": 19,
                            "openedAt": "-26M",
                        },
                    ],
                    "closedLoans": [],
                    "inquiries30d": 0,
                    "rejectedApplications90d": 0,
                },
                # Директор и владелец — один человек: закрытый кредит и карта, история 5 лет
                "director": clean_person(),
                "owner": clean_person(),
            },
            "contracts": [
                # Действующий госконтракт на поставку медтоваров, 12 млн, оплачено 0, оплата
                # через 3 месяца: нужен карточке CONTRACT встречного (30-10, T-297)
                {
                    "customer": {"name": "ГБУЗ «Городская клиническая больница № 7»"},
                    "subject": "Поставка медицинских изделий для хирургического отделения",
                    "priceRub": 12000000,
                    "concluded": "-2M",
                    "executionIn": "+2M",
                    "paymentIn": "+3M",
                    "status": "IN_PROGRESS",
                    "paidRub": 0,
                },
                # Один исполненный контракт, оплачен полностью (допущение: сумма и сроки)
                {
                    "customer": {"name": "ГАУЗ «Областная детская больница»"},
                    "subject": "Поставка расходных материалов для лабораторий",
                    "priceRub": 7800000,
                    "concluded": "-14M",
                    "executionIn": "-9M",
                    "paymentIn": "-8M",
                    "status": "EXECUTED",
                    "paidRub": 7800000,
                },
            ],
            "application": {
                "productCode": "WORKING_CAPITAL",
                "amountRub": 8000000,
                "termMonths": 12,
                "collateral": None,
                # У ООО поручительство владельца стандартное, клиент его не указывает (10.5)
                "guarantor": None,
            },
            # Платёж 739 163 при потоке 1 200 000 и текущих 600 000 даёт DSCR 0,90 (30-17)
            "expectedOutcome": "COUNTER_OFFER",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["DSCR_LOW"],
            "users": [
                {
                    "login": "orlov-p",
                    "role": "DIRECTOR",
                    "personRef": "orlov",
                    "inn": ORLOV_INN,
                    "fullName": "Орлов Пётр Игоревич",
                }
            ],
            "raw": {
                "tax": {
                    "financials": [
                        # 2025: 2400 = 13 200 000 и 2330 = 1 200 000 вместо «прибыль ~14,4»:
                        # поток ровно (13,2 + 1,2) / 12 = 1 200 000 в месяц. Баланс сходится:
                        # 1600 = 1100 + 1200 = 1300 + 1400 + 1500. Допущение: 2200, баланс и
                        # 1400 оракул не задаёт (1400 не больше остатков кредитов на 31.12.2025).
                        _statement(
                            2025,
                            "FULL",
                            {
                                "1100": 14000000,
                                "1200": 46000000,
                                "1300": 38000000,
                                "1400": 3000000,
                                "1500": 19000000,
                                "1600": 60000000,
                                "2110": 180000000,
                                "2200": 18000000,
                                "2330": 1200000,
                                "2400": 13200000,
                            },
                        ),
                        # 2024: оракул задаёт только 2110 = 180 000 000; остальное допущение
                        # (значения 2400 и 2330 — как в ручных входах ядра)
                        _statement(
                            2024,
                            "FULL",
                            {
                                "1100": 13000000,
                                "1200": 42000000,
                                "1300": 34000000,
                                "1400": 4000000,
                                "1500": 17000000,
                                "1600": 55000000,
                                "2110": 180000000,
                                "2200": 16500000,
                                "2330": 1100000,
                                "2400": 12000000,
                            },
                        ),
                    ],
                    "taxProfile": {
                        # Доход в «Прозрачном бизнесе» равен строке 2110, расходы = 2110 − 2400
                        "incomeExpenses": {
                            "year": 2025,
                            "incomeRub": 180000000,
                            "expensesRub": 166800000,
                        }
                    },
                }
            },
        }
    )


def _stankoprom() -> ScenarioSpec:
    """Металлообработка, не клиент: крупная сумма с залогом идёт на ручное рассмотрение."""
    # Директор и владелец — один человек, у него один субъект БКИ: блоки director и owner
    # обязаны совпасть (противоречие — 422). Карта 300 000 / 90 000 (платёж 5% = 4 500) и
    # закрытый потребкредит открыт 12.05.2022 — история старше 24 месяцев (30-17).
    kuznetsov_bki = {
        "historyYears": None,
        "activeLoans": [{"kind": "CREDIT_CARD", "limitRub": 300000, "balanceRub": 90000}],
        "closedLoans": [
            {
                "kind": "CONSUMER_LOAN",
                "amountRub": 250000,
                "openedAt": "2022-05-12",
                "closedAt": "2024-05-12",
                "repayment": "ANNUITY",
            }
        ],
        "inquiries30d": 0,
        "rejectedApplications90d": 0,
    }
    return ScenarioSpec.model_validate(
        {
            "code": "stankoprom",
            "title": "ООО «СтанкоПром» — крупная сумма с залогом, ручное рассмотрение",
            "builtinVersion": 1,
            "preset": "LLC_HEALTHY",
            "company": {
                "form": "LLC",
                "inn": STANKOPROM_INN,
                "ogrn": "1170000004569",
                "kpp": "001701001",
                "name": "СтанкоПром",
                "registrationDate": "2017-03-14",
                "okved": "25.62",
                "regionCode": "66",
            },
            "people": {
                "director": {
                    "ref": "kuznetsov",
                    "inn": KUZNETSOV_INN,
                    "fullName": "Кузнецов Игорь Петрович",
                    "birthDate": "1979-02-11",
                    "sharePercent": 100,
                }
            },
            "finance": {
                "avgMonthlyRevenueRub": 35000000,
                "noisePercent": 0,
                "netMarginPercent": 8,
                "taxRegime": "OSNO",
                "hasStatements": True,
                # Допущение: 60 человек, как в примере 10.5; малое предприятие
                "headcount": 60,
            },
            "bank": {"isCustomer": False},
            "bki": {
                "company": {
                    # Два закрытых кредита, активных нет. historyYears снят: иначе генератор
                    # допишет ещё один закрытый кредит к двум из оракула. История выходит
                    # 5 лет 11 месяцев (самый ранний открыт 16.11.2020), фикстура ядра — 84.
                    "historyYears": None,
                    "activeLoans": [],
                    "closedLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 22000000,
                            "openedAt": "2020-11-16",
                            "closedAt": "2026-03-20",
                            "repayment": "BULLET",
                            "secured": True,
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 9000000,
                            "openedAt": "2021-06-10",
                            "closedAt": "2025-06-12",
                            "repayment": "BULLET",
                        },
                    ],
                    "inquiries30d": 0,
                    "rejectedApplications90d": 0,
                },
                "director": kuznetsov_bki,
                "owner": dict(kuznetsov_bki),
            },
            "application": {
                "productCode": "INVESTMENT",
                "amountRub": 15000000,
                "termMonths": 60,
                "collateral": {
                    "description": "Покупаемая линия оборудования",
                    "valueRub": 25000000,
                },
                "guarantor": None,
            },
            "expectedOutcome": "MANUAL_REVIEW",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"],
            "users": [
                {
                    "login": "kuznetsov",
                    "role": "DIRECTOR",
                    "personRef": "kuznetsov",
                    "inn": KUZNETSOV_INN,
                    "fullName": "Кузнецов Игорь Петрович",
                },
                {
                    "login": "belova",
                    "role": "ACCOUNTANT",
                    "fullName": "Белова Ольга Николаевна",
                    "inn": BELOVA_INN,
                    "powerOfAttorney": True,
                },
            ],
            "raw": {
                "tax": {
                    "financials": [
                        # Строки из примера 10.5. Долг 22 млн (1400) на конец 2025 года — кредит
                        # на 22 млн, закрытый в марте 2026; на конец 2024 — 31 млн вместе с 9 млн,
                        # закрытыми в июне 2025
                        _statement(
                            2025,
                            "FULL",
                            {
                                "1100": 182000000,
                                "1200": 141000000,
                                "1300": 196000000,
                                "1400": 22000000,
                                "1500": 105000000,
                                "1600": 323000000,
                                "2110": 420000000,
                                "2200": 41500000,
                                "2330": 1900000,
                                "2400": 30700000,
                            },
                        ),
                        _statement(
                            2024,
                            "FULL",
                            {
                                "1100": 171000000,
                                "1200": 128000000,
                                "1300": 165300000,
                                "1400": 31000000,
                                "1500": 102700000,
                                "1600": 299000000,
                                "2110": 388000000,
                                "2200": 36900000,
                                "2330": 3100000,
                                "2400": 27400000,
                            },
                        ),
                    ],
                    "taxProfile": {
                        "incomeExpenses": {
                            "year": 2025,
                            "incomeRub": 420000000,
                            "expensesRub": 389300000,
                        }
                    },
                }
            },
        }
    )


def _zarya() -> ScenarioSpec:
    """АО-агрохолдинг, клиент, сезонные обороты: кредитная линия с залогом, ручное → одобрено."""
    return ScenarioSpec.model_validate(
        {
            "code": "zarya",
            "title": "АО «Агрохолдинг Заря» — кредитная линия на посевную, ручное рассмотрение",
            "builtinVersion": 1,
            "preset": "LLC_HEALTHY",
            "company": {
                "form": "JSC",
                "name": "Агрохолдинг Заря",
                "inn": ZARYA_INN,
                # «24 года» (30-17); дата из ручных входов ядра. Акционеров ЕГРЮЛ не показывает:
                # founders пуст, владельца-человека и поручителя нет
                "registrationDate": "2002-06-01",
                "okved": "01.11",
                "regionCode": "23",
            },
            "people": {
                "director": {
                    "ref": "gromov",
                    "inn": GROMOV_INN,
                    "fullName": "Громов Виктор Иванович",
                    "birthDate": "1972-04-17",
                }
            },
            "finance": {
                # Сезонность AGRO генератора — ровно формула 30-17:
                # 650 000 000 / 12 × (1 + 0,6 · sin(2π (m − 6) / 12)); ЕСХН, НДС 0.
                # 54 166 667 — это 650 млн / 12 с округлением; пик сентябрь 86 666 667,
                # минимум март 21 666 667. Остаток месяца 10% поступлений (маржа 10%).
                "avgMonthlyRevenueRub": 54166667,
                "seasonality": "AGRO",
                "noisePercent": 0,
                "netMarginPercent": 10,
                "taxRegime": "ESHN",
                "hasStatements": True,
                # 90 человек при выручке 650 млн: категория МСП — малое
                "headcount": 90,
            },
            # Клиент с 2018 года (≥ 36 мес.). Остаток на счёте оракул не задаёт: допущение
            # 28 000 000 (после уборки урожая)
            "bank": {"isCustomer": True, "customerSinceMonths": 100, "balanceRub": 28000000},
            "bki": {
                "company": {
                    # Платежи 1 500 000 = кредиты 900 000 + 5% от использованных линий 600 000;
                    # долг 40 000 000 = кредиты 28 000 000 + линии 12 000 000. Разбивка на
                    # кредиты и линии — допущение, суммы подобраны под оракул, просрочек нет.
                    "historyYears": None,
                    "activeLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 17607000,
                            "termMonths": 76,
                            "ratePercent": 19,
                            "openedAt": "-26M",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 19755000,
                            "termMonths": 65,
                            "ratePercent": 20,
                            "openedAt": "-26M",
                            "secured": True,
                        },
                        # Три линии: использовано 6 + 4 + 2 = 12 млн, платежи 5% = 600 000
                        {
                            "kind": "CREDIT_LINE",
                            "limitRub": 20000000,
                            "balanceRub": 6000000,
                            "termMonths": 60,
                            "openedAt": "-30M",
                        },
                        {
                            "kind": "CREDIT_LINE",
                            "limitRub": 10000000,
                            "balanceRub": 4000000,
                            "termMonths": 60,
                            "openedAt": "-28M",
                        },
                        {
                            "kind": "CREDIT_LINE",
                            "limitRub": 8000000,
                            "balanceRub": 2000000,
                            "termMonths": 48,
                            "openedAt": "-27M",
                        },
                    ],
                    # «Много кредитных линий за 10 лет, всё вовремя»: шесть закрытых кредитов,
                    # самый ранний открыт 16.10.2006 (история 20 лет, как в ручных входах ядра).
                    # Допущение: суммы и сроки оракул не задаёт.
                    "closedLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 3000000,
                            "openedAt": "2006-10-16",
                            "closedAt": "2009-10-16",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 8000000,
                            "openedAt": "2009-04-10",
                            "closedAt": "2013-04-10",
                            "secured": True,
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 15000000,
                            "openedAt": "2013-06-05",
                            "closedAt": "2017-06-05",
                            "secured": True,
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 20000000,
                            "openedAt": "2016-03-14",
                            "closedAt": "2020-03-14",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 30000000,
                            "openedAt": "2019-05-20",
                            "closedAt": "2023-05-20",
                            "secured": True,
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 12000000,
                            "openedAt": "2021-09-08",
                            "closedAt": "2025-09-08",
                        },
                    ],
                    "inquiries30d": 0,
                    "rejectedApplications90d": 0,
                },
                # У АО владельца-человека нет, блок owner задать нельзя (10.2)
                "director": clean_person(),
                "owner": None,
            },
            "application": {
                "productCode": "CREDIT_LINE",
                "amountRub": 20000000,
                "termMonths": 12,
                "collateral": {"description": "Сельхозтехника", "valueRub": 30000000},
                "guarantor": None,
            },
            "expectedOutcome": "MANUAL_REVIEW",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["AMOUNT_ABOVE_AUTO_LIMIT", "COLLATERAL_REVIEW"],
            "users": [
                {
                    "login": "gromov",
                    "role": "DIRECTOR",
                    "personRef": "gromov",
                    "inn": GROMOV_INN,
                    "fullName": "Громов Виктор Иванович",
                }
            ],
            "raw": {
                "tax": {
                    "financials": [
                        # 2025: 2110 = 650 млн, 2400 = 65 млн, 2330 = 4 млн; 2024: 650 / 65 / 4,5.
                        # Допущение: 2200, баланс и 1400 оракул не задаёт (1400 не больше остатков
                        # кредитов на 31.12.2025, 2330 в пределах 2-25% среднего долга за год)
                        _statement(
                            2025,
                            "FULL",
                            {
                                "1100": 220000000,
                                "1200": 180000000,
                                "1300": 250000000,
                                "1400": 20000000,
                                "1500": 130000000,
                                "1600": 400000000,
                                "2110": 650000000,
                                "2200": 80000000,
                                "2330": 4000000,
                                "2400": 65000000,
                            },
                        ),
                        _statement(
                            2024,
                            "FULL",
                            {
                                "1100": 210000000,
                                "1200": 170000000,
                                "1300": 235000000,
                                "1400": 22000000,
                                "1500": 123000000,
                                "1600": 380000000,
                                "2110": 650000000,
                                "2200": 79000000,
                                "2330": 4500000,
                                "2400": 65000000,
                            },
                        ),
                    ],
                    "taxProfile": {
                        # ЕСХН: доход равен 2110, расходы = 2110 − 2400
                        "incomeExpenses": {
                            "year": 2025,
                            "incomeRub": 650000000,
                            "expensesRub": 585000000,
                        }
                    },
                }
            },
        }
    )


def large_personas() -> list[ScenarioSpec]:
    """Персоны T-133. Новые независимые модели на каждый вызов."""
    return [_snabkontrakt(), _stankoprom(), _zarya()]
