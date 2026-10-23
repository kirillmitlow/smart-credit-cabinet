"""Встроенные персоны T-132 и T-134: vektor, orlov, romashka, garipov, quick-start.

Формат — тот же `ScenarioSpec`, что у Соколовой в `builtin.py` (T-131). Точные входы взяты из
оракула 30-17 и ручных входов ядра `api/tests/fixtures/core_personas.py`. Что оракул не задаёт,
здесь названо явным допущением в комментарии рядом с числом. Месяцы и относительные даты
вычисляются из часов стенда, реквизиты и абсолютные даты остаются постоянными.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.common.clock import last_full_month, last_reporting_year
from app.common.reldate import add_months
from app.roles.scenarios.finance_series import rub
from app.roles.scenarios.schemas import ScenarioSpec

VEKTOR_INN = "0018889990"
ORLOV_INN = "001211122200"
ROMASHKA_INN = "0015557771"
GARIPOV_INN = "001298765490"
QUICK_START_INN = "0012221117"

# Личные ИНН: региона 00 с верной контрольной суммой; свои у каждой персоны.
LEBEDEV_INN = "001310000683"  # директор и владелец «Вектора»
MOROZOV_INN = "001310000436"  # директор и владелец «Ромашки» (подписант в примере 6.1)
SOKOLOV_INN = "001310001172"  # директор, владелец и поручитель «Быстрого старта»

# Просрочка Ромашки по 30-17: 94 дня на 452 000 (4 неоплаченных платежа по 113 000)
ROMASHKA_OVERDUE_DAYS = 94


def clean_person() -> dict[str, Any]:
    """Чистая личная история как `clean_person()` в фикстурах ядра.

    Закрытый потребкредит и карта без долга, история 60 месяцев. Больше двух лет и два
    обязательства нужны, чтобы класс истории не скатился в `THIN_CLEAN` (30-17).
    """
    return {
        "historyYears": 5,
        "closedLoans": [
            {"kind": "CONSUMER_LOAN", "amountRub": 300000, "openedAt": "-5y", "closedAt": "-3y"}
        ],
        "activeLoans": [{"kind": "CREDIT_CARD", "limitRub": 100000, "balanceRub": 0}],
        "inquiries30d": 0,
        "rejectedApplications90d": 0,
    }


def _flat_turnover(
    today: date, months: int, incoming_net: int, surplus: int, payers_in: int, payers_out: int
) -> list[dict[str, Any]]:
    """Плоский ряд без шума: полные месяцы, `incomingNetRub` ровно как в 30-17.

    `incomingRub` на 0,75% выше, округление до 100 ₽ (10.3, noisePercent: 0).
    """
    last = last_full_month(today)
    gross = rub(Decimal(incoming_net) * Decimal("1.0075"), 100)
    return [
        {
            "month": add_months(last, offset).strftime("%Y-%m"),
            "incomingRub": max(incoming_net, gross),
            "incomingNetRub": incoming_net,
            "outgoingRub": incoming_net - surplus,
            "counterpartiesIn": payers_in,
            "counterpartiesOut": payers_out,
        }
        for offset in range(1 - months, 1)
    ]


def _vektor() -> ScenarioSpec:
    """ООО в ликвидации: стоп `COMPANY_NOT_ACTIVE`, остальное чисто (30-17)."""
    return ScenarioSpec.model_validate(
        {
            "code": "vektor",
            "title": "ООО «Вектор» — компания в ликвидации, отказ по реестру",
            "builtinVersion": 1,
            "preset": "LLC_HEALTHY",
            "company": {
                "form": "LLC",
                "name": "Вектор",
                "inn": VEKTOR_INN,
                # «4 года» по 30-17; регистрация относительная: персона не стареет
                "ageMonths": 48,
                "status": "LIQUIDATING",
                "unreliableAddress": True,
                "okved": "47.19",
                "regionCode": "78",
            },
            "people": {
                "director": {
                    "ref": "lebedev",
                    "inn": LEBEDEV_INN,
                    "fullName": "Лебедев Антон Сергеевич",
                    "birthDate": "1985-03-21",
                    "sharePercent": 100,
                }
            },
            "finance": {
                # Допущение: оракул выручку Вектора не задаёт (стоп срабатывает до расчёта),
                # взята скромная розница. Отчётности нет: ядро её не читает при стопе.
                "avgMonthlyRevenueRub": 2500000,
                "noisePercent": 0,
                "netMarginPercent": 8,
                "taxRegime": "USN_INCOME",
                "hasStatements": False,
                "headcount": 8,
            },
            "bank": {"isCustomer": False},
            "bki": {
                "company": {
                    # Один закрытый кредит, история 40 месяцев (фикстура ядра);
                    # historyYears пресета снимаем, иначе добавится лишний кредит
                    "historyYears": None,
                    "activeLoans": [],
                    "closedLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 1000000,
                            "openedAt": "-40M",
                            "closedAt": "-16M",
                        }
                    ],
                    "inquiries30d": 0,
                    "rejectedApplications90d": 0,
                },
                "director": clean_person(),
                "owner": clean_person(),
            },
            "application": {
                "productCode": "EXPRESS",
                "amountRub": 2000000,
                "termMonths": 12,
                "collateral": None,
                "guarantor": None,
            },
            "expectedOutcome": "REJECTED",
            "expectedReasonCodes": ["COMPANY_NOT_ACTIVE"],
            "users": [
                {
                    "login": "lebedev",
                    "role": "DIRECTOR",
                    "personRef": "lebedev",
                    "inn": LEBEDEV_INN,
                    "fullName": "Лебедев Антон Сергеевич",
                }
            ],
        }
    )


def _orlov() -> ScenarioSpec:
    """Самозанятый: в ЕГРИП его нет, НПД `status: true`; БКИ и АБС пусты, учётки нет."""
    return ScenarioSpec.model_validate(
        {
            "code": "orlov",
            "title": "Орлов — самозанятый фотограф, бизнес-кредит недоступен",
            "builtinVersion": 1,
            "preset": "SELF_EMPLOYED",
            "company": {
                "form": "SELF_EMPLOYED",
                "name": "Орлов Михаил Игоревич",
                "inn": ORLOV_INN,
                # Допущение: самозанятый с осени 2024; даты оракул не задаёт
                "ageMonths": 24,
                "okved": "74.20",
                "regionCode": "63",
            },
            "application": {
                "productCode": None,
                "amountRub": 300000,
                "termMonths": None,
                "collateral": None,
                "guarantor": None,
            },
            "expectedOutcome": "NOT_ELIGIBLE",
            "expectedReasonCodes": ["SELF_EMPLOYED"],
            # Входа нет: до заявки не доходит, вход по ИНН даёт объяснение (30-17)
            "users": [],
        }
    )


def _romashka(today: date) -> ScenarioSpec:
    """Налоговый долг 14,53% месячной выручки и просрочка 94 дня (пример 6.1, 30-17)."""
    # Первый неоплаченный платёж приходится ровно на «сегодня − 94 дня», платёж 29-й по счёту:
    # 28 платежей внесены (остаток 837 000), 4 не внесены (4 × 113 000 = 452 000), как в 6.1.
    # День платежа не больше 28 (due_date прижимает к 28-му), иначе дни просрочки чуть больше.
    since = today - timedelta(days=ROMASHKA_OVERDUE_DAYS)
    if since.day > 28:
        since = since.replace(day=28)
    overdue_days = (today - since).days
    opened = add_months(since, -29)
    year = last_reporting_year(today)
    return ScenarioSpec.model_validate(
        {
            "code": "romashka",
            "title": "ООО «Ромашка» — налоговый долг и просрочка 94 дня, отказ",
            "builtinVersion": 1,
            "preset": "PROBLEM_DEBTOR",
            "company": {
                "form": "LLC",
                "name": "Ромашка",
                "inn": ROMASHKA_INN,
                # ОГРН из примера 6.1; год ОГРН (19) совпадает с годом регистрации
                "ogrn": "1190000007890",
                "registrationDate": "2019-10-01",
                "okved": "46.73",
                "regionCode": "50",
            },
            "people": {
                "director": {
                    "ref": "morozov",
                    "inn": MOROZOV_INN,
                    "fullName": "Морозов Олег Викторович",
                    "birthDate": "1981-05-14",
                    "sharePercent": 100,
                }
            },
            "finance": {
                # 95 000 000 / 12 = 7 916 667 в месяц; точная строка 2110 — в raw ниже
                "avgMonthlyRevenueRub": 7916667,
                "noisePercent": 0,
                "netMarginPercent": 4,
                "taxRegime": "USN_INCOME_MINUS_EXPENSES",
                "hasStatements": True,
                # Допущение: 18 человек, чтобы категория МСП была «малое» (10.5), а не «микро»
                "headcount": 18,
            },
            "tax": {"taxDebtRub": 1150000},
            "bank": {"isCustomer": False},
            "bki": {
                "company": {
                    "historyYears": None,
                    "activeLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 3000000,
                            "termMonths": 36,
                            "ratePercent": 21,
                            "openedAt": opened.isoformat(),
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 4000000,
                            "termMonths": 24,
                            "ratePercent": 21,
                            "openedAt": "-19M",
                            "secured": True,
                        },
                    ],
                    # Три закрытых кредита раньше 2025 года: 2330 и 1400 за 2025 считаются
                    # только по двум активным. Самый ранний открыт через две недели после
                    # регистрации: история 84 месяца.
                    "closedLoans": [
                        {
                            "kind": "LOAN",
                            "amountRub": 1000000,
                            "openedAt": "2019-10-15",
                            "closedAt": "2021-10-15",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 2000000,
                            "openedAt": "2021-03-10",
                            "closedAt": "2023-03-10",
                        },
                        {
                            "kind": "LOAN",
                            "amountRub": 2500000,
                            "openedAt": "2022-09-05",
                            "closedAt": "2024-09-05",
                        },
                    ],
                    "currentOverdueDays": overdue_days,
                    "inquiries30d": 6,
                    "rejectedApplications90d": 2,
                },
                "director": clean_person(),
                "owner": clean_person(),
            },
            "application": {
                "productCode": "WORKING_CAPITAL",
                "amountRub": 3000000,
                "termMonths": 6,
                "collateral": None,
                "guarantor": None,
            },
            "expectedOutcome": "REJECTED",
            # Главный код первый (порядок 30-04); второй входит в набор
            "expectedReasonCodes": ["TAX_ARREARS_HIGH", "CURRENT_OVERDUE_90"],
            "users": [
                {
                    "login": "morozov",
                    "role": "DIRECTOR",
                    "personRef": "morozov",
                    "inn": MOROZOV_INN,
                    "fullName": "Морозов Олег Викторович",
                }
            ],
            "raw": {
                "tax": {
                    "financials": [
                        {
                            "year": year,
                            "formType": "SIMPLIFIED",
                            "lines": {
                                # Допущение: баланс подобран так, чтобы сходился (1600 = 1100 +
                                # 1200 = 1300 + 1400 + 1500); оракул задаёт только 2110, 2330,
                                # 1400 и (через ядро) 2400 = 4 млн, 2200 — на усмотрение
                                "1100": 9000000,
                                "1200": 19000000,
                                "1300": 11500000,
                                "1400": 500000,
                                "1500": 16000000,
                                "1600": 28000000,
                                "2110": 95000000,
                                "2200": 5300000,
                                "2330": 600000,
                                "2400": 4000000,
                            },
                        }
                    ],
                    "taxProfile": {
                        # Как в примере 5.1: пени 42 000 не считаются (30-17), одно
                        # правонарушение со штрафом 5 000, налоги уплачены
                        "debts": {"penaltiesRub": 42000},
                        # Доход ПБ равен строке 2110 (правило 10.3), расходы = 2110 − 2400
                        "incomeExpenses": {
                            "year": year,
                            "incomeRub": 95000000,
                            "expensesRub": 91000000,
                        },
                        "taxOffenses": {"year": year, "count": 1, "finesRub": 5000},
                        "taxesPaid": [
                            {"year": year, "totalRub": 3410000},
                            {"year": year - 1, "totalRub": 3120000},
                        ],
                    },
                }
            },
        }
    )


def _garipov() -> ScenarioSpec:
    """ИП на патенте, не клиент: оборотов нет, отчётности нет → `NEEDS_INFO`, потом выписка."""
    return ScenarioSpec.model_validate(
        {
            "code": "garipov",
            "title": "ИП Гарипов — барбершоп на патенте, нужна выписка из другого банка",
            "builtinVersion": 1,
            "preset": "IP_HEALTHY",
            "company": {
                "form": "IP",
                "name": "Гарипов Рустам Ильдарович",
                "inn": GARIPOV_INN,
                # 61 месяц, не на границе 60 (30-17); возраст относительный
                "ageMonths": 61,
                "okved": "96.02",
                "regionCode": "77",
            },
            "finance": {
                # Эти числа попадут в выписку другого банка (10.8), а не в АБС: Гарипов не клиент.
                # Поступления ровно 700 000, списания 600 000 (остаток 100 000), без шума;
                # годовая 8,4 млн в пределах лимита патента.
                "avgMonthlyRevenueRub": 700000,
                "noisePercent": 0,
                "netMarginPercent": 13,
                "minMonthlySurplusRub": 100000,
                "taxRegime": "PSN",
                "hasStatements": False,
                "headcount": 3,
            },
            # Не клиент: счёта и оборотов нет; остальные поля пресета снимаем
            "bank": {"isCustomer": False, "customerSinceMonths": None, "balanceRub": None},
            "bki": {
                # ИП: личная история и есть история бизнеса. Один закрытый кредит, открыт
                # 4 года назад, закрыт 3 года назад, активных нет
                "owner": {
                    "historyYears": 4,
                    "activeLoans": [],
                    "closedLoans": [
                        {"kind": "LOAN", "amountRub": 800000, "openedAt": "-4y", "closedAt": "-3y"}
                    ],
                    "inquiries30d": 0,
                    "rejectedApplications90d": 0,
                }
            },
            "application": {
                "productCode": "EXPRESS",
                "amountRub": 1500000,
                "termMonths": 36,
                "collateral": None,
                "guarantor": None,
            },
            "expectedOutcome": "NEEDS_INFO",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["REVENUE_UNKNOWN"],
            "users": [
                {
                    "login": "garipov",
                    "role": "DIRECTOR",
                    "personRef": "self",
                    "inn": GARIPOV_INN,
                    "fullName": "Гарипов Рустам Ильдарович",
                }
            ],
        }
    )


def _quick_start(today: date) -> ScenarioSpec:
    """ООО 3 месяца, клиент 3 месяца; владелец-директор — будущий поручитель."""
    return ScenarioSpec.model_validate(
        {
            "code": "quick-start",
            "title": "ООО «Быстрый старт» — бизнесу 3 месяца, встречное с поручительством",
            "builtinVersion": 1,
            "preset": "STARTUP",
            "company": {
                "form": "LLC",
                "name": "Быстрый старт",
                "inn": QUICK_START_INN,
                # Возраст 3 месяца и в день защиты, и через полгода (проверка сдвигом APP_TODAY)
                "ageMonths": 3,
                "okved": "62.01",
                "regionCode": "77",
            },
            "people": {
                "director": {
                    # Ссылка owner: директор, единственный учредитель (100%), владелец и
                    # поручитель шагом позже — один человек
                    "ref": "owner",
                    "inn": SOKOLOV_INN,
                    "fullName": "Соколов Дмитрий Андреевич",
                    "birthDate": "1990-06-12",
                    "sharePercent": 100,
                }
            },
            "finance": {
                "avgMonthlyRevenueRub": 700000,
                "noisePercent": 0,
                "netMarginPercent": 15,
                "minMonthlySurplusRub": 105000,
                "taxRegime": "AUSN",
                "hasStatements": False,
            },
            "bank": {"isCustomer": True, "customerSinceMonths": 3, "balanceRub": 300000},
            "bki": {
                # У компании истории нет: NOT_FOUND (historyYears: 0 из пресета)
                "company": {"historyYears": 0},
                # Чистая личная история владельца-поручителя
                "owner": clean_person(),
            },
            "application": {
                "productCode": "EXPRESS",
                "amountRub": 1000000,
                "termMonths": 24,
                "collateral": None,
                # Первичный запрос без поручителя; поручитель owner добавляется после
                # принятия встречного (10.5, D-035)
                "guarantor": None,
            },
            "expectedOutcome": "COUNTER_OFFER",
            "expectedFinalOutcome": "APPROVED",
            "expectedReasonCodes": ["BUSINESS_TOO_YOUNG"],
            "users": [
                {
                    "login": "sokolov",
                    "role": "DIRECTOR",
                    "personRef": "owner",
                    "inn": SOKOLOV_INN,
                    "fullName": "Соколов Дмитрий Андреевич",
                }
            ],
            "raw": {
                # Допущение: 10 плательщиков, как в ручных входах ядра (оракул число не
                # задаёт; генератор дал бы 5). Ряд 700 000 × 3, остаток месяца 105 000
                "bankCore": {"turnover": _flat_turnover(today, 3, 700000, 105000, 10, 11)}
            },
        }
    )


def simple_personas(today: date) -> list[ScenarioSpec]:
    """Персоны T-132 и T-134. Новые независимые модели на каждый вызов."""
    return [_vektor(), _orlov(), _romashka(today), _garipov(), _quick_start(today)]
