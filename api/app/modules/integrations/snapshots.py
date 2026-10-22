"""Разбор сохранённого ответа источника обратно во внутреннюю модель (T-272, 50-08).

Конвейер хранит ответы моков как есть (`source_snapshots.payload`). Чтобы шаги можно было
продолжить после обрыва (и воспроизвести решение), ответ разбирается заново теми же функциями
маппинга, что и при живом вызове. Новых форматов здесь нет: это таблица «ресурс → разбор».
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from app.modules.integrations.bank_core import map_customer, map_loans, map_screening, map_turnover
from app.modules.integrations.credit_bureau import map_report
from app.modules.integrations.registry import map_bankruptcies, map_company, map_roles
from app.modules.integrations.tax import (
    SelfEmployedStatus,
    _NpdDto,
    map_blocks,
    map_contracts,
    map_financials,
    map_sme,
    map_tax_profile,
)

_PARSERS: dict[str, Callable[[object], Any]] = {
    "registry:company": map_company,
    "registry:roles": map_roles,
    "registry:bankruptcies": map_bankruptcies,
    "tax:profile": map_tax_profile,
    "tax:financials": map_financials,
    "tax:sme": map_sme,
    "tax:blocks": map_blocks,
    "tax:contracts": map_contracts,
    "bank_core:customer": map_customer,
    "bank_core:turnover": map_turnover,
    "bank_core:loans": map_loans,
    "bank_core:compliance": map_screening,
    "credit_bureau:report": map_report,
}


def known_resources() -> frozenset[str]:
    return frozenset(_PARSERS) | {"tax:npd"}


def parse_snapshot(resource: str, payload: object, *, inn: str = "", on: date | None = None) -> Any:
    """Ответ источника как есть → внутренняя модель. `inn` и `on` нужны только для `tax:npd`."""
    if resource == "tax:npd":
        if on is None:
            raise ValueError("Для tax:npd нужна дата проверки")
        return SelfEmployedStatus(inn, _NpdDto.model_validate(payload).status, on)
    try:
        parser = _PARSERS[resource]
    except KeyError:
        raise ValueError(f"Неизвестный ресурс снимка: {resource}") from None
    return parser(payload)
