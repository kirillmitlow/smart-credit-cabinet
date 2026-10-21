"""Справочник кодов причин (30-12) и порядок их показа.

Код видит андеррайтер и тест; клиенту показываются тексты (`texts_ru.py`), не коды.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.decisioning.types import ParamValue, ReasonCode, ReasonKind

K = ReasonKind

CODE_KINDS: dict[str, ReasonKind] = {
    # допуск и данные
    "SELF_EMPLOYED": K.DATA,
    "DATA_INCOMPLETE": K.DATA,
    "REVENUE_UNKNOWN": K.DATA,
    # стоп-факторы (порядок — как в 30-04)
    "COMPANY_NOT_ACTIVE": K.STOP,
    "AML_LIST": K.STOP,
    "BANKRUPTCY": K.STOP,
    "FORBIDDEN_INDUSTRY": K.STOP,
    "DUPLICATE_APPLICATION": K.STOP,
    "TAX_ARREARS_HIGH": K.STOP,
    "CURRENT_OVERDUE_90": K.STOP,
    # флаги
    "MASS_REGISTRATION": K.FLAG,
    "OVERDUE_30_89": K.FLAG,
    "DATA_MISMATCH": K.FLAG,
    "TURNOVER_ANOMALY": K.FLAG,
    "SOURCE_UNAVAILABLE": K.FLAG,
    "PIPELINE_ERROR": K.FLAG,
    # ограничения и деньги
    "BUSINESS_TOO_YOUNG": K.CONSTRAINT,
    "DSCR_LOW": K.CONSTRAINT,
    "STRESS_DSCR_LOW": K.CONSTRAINT,
    "DEBT_TOO_HIGH": K.CONSTRAINT,
    "LIMIT_ABOVE_CAP": K.CONSTRAINT,
    # правила продукта
    "COLLATERAL_REQUIRED": K.PRODUCT,
    "PRODUCT_AGE_MIN": K.PRODUCT,
    "NOT_BANK_CLIENT": K.PRODUCT,
    "GRADE_NOT_ALLOWED": K.PRODUCT,
    "CONTRACT_INVALID": K.PRODUCT,
    "AMOUNT_OUT_OF_RANGE": K.PRODUCT,
    # маршрут
    "GRADE_NEEDS_REVIEW": K.ROUTE,
    "AMOUNT_ABOVE_AUTO_LIMIT": K.ROUTE,
    "COLLATERAL_REVIEW": K.ROUTE,
    "NEAR_THRESHOLD": K.ROUTE,
    "GRADE_CAPPED": K.ROUTE,
    # общий исход
    "RISK_TOO_HIGH": K.OUT,
    "NO_OFFER_FOUND": K.OUT,
}

# Порядок кодов в ответе (30-17): допуск → стопы → флаги → ограничение → деньги → продукт →
# маршрут → итог → информационные
_ORDER: dict[str, int] = {code: i for i, code in enumerate(CODE_KINDS)}
# Итоговый отказ показываем первым (главный код), информационный GRADE_CAPPED — последним
_ORDER.update({"RISK_TOO_HIGH": -2, "NO_OFFER_FOUND": -1, "GRADE_CAPPED": 10_000})

# Порядок ручных причин внутри маршрута задан 30-11: GRADE_NEEDS_REVIEW, AMOUNT_ABOVE_AUTO_LIMIT,
# COLLATERAL_REVIEW, NEAR_THRESHOLD — он же порядок объявления выше.


def make(code: str, **params: ParamValue) -> ReasonCode:
    return ReasonCode(code=code, kind=CODE_KINDS[code], params=dict(params))


def order_reasons(reasons: Iterable[ReasonCode]) -> tuple[ReasonCode, ...]:
    """Устойчивая сортировка без точных повторов; главный код — первый по порядку справочника.

    Один код с разными параметрами (например, `NEAR_THRESHOLD` по DSCR и по стрессу) остаётся.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[ReasonCode] = []
    for r in reasons:
        key = (r.code, repr(sorted(r.params.items(), key=lambda kv: kv[0])))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return tuple(sorted(unique, key=lambda r: _ORDER[r.code]))
