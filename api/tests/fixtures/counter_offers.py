"""Помощники проверок встречных (T-297): повторная подача карточки как обычного запроса."""

from __future__ import annotations

from dataclasses import replace

from app.modules.decisioning import decide
from app.modules.decisioning.types import (
    Collateral,
    DecisionInput,
    DecisionResult,
    Outcome,
    Variant,
)

# INV-40: «не хуже MANUAL_REVIEW»; `NEEDS_INFO` и `NOT_ELIGIBLE` для карточки тоже ошибка
PASSING = frozenset({Outcome.APPROVED, Outcome.MANUAL_REVIEW})


def resubmit(inp: DecisionInput, variant: Variant) -> DecisionResult:
    """Условия карточки как новая заявка; залог, который просит карточка, прикладывается."""
    app = replace(
        inp.application,
        product=variant.product,
        amount_rub=variant.amount_rub,
        term_months=variant.term_months,
    )
    if variant.security_required and app.collateral is None:
        app = replace(app, collateral=Collateral("залог", variant.amount_rub * 2))
    return decide(replace(inp, application=app))
