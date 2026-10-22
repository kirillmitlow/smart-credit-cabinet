"""Допуск и полнота данных (T-295, шаги 1 и 3а, 30-01): `NOT_ELIGIBLE` и `NEEDS_INFO`.

Отказ не выдаётся из-за отсутствия данных: нехватка превращается в понятный запрос клиенту.
Недоступность обязательного источника здесь только фиксируется как `SOURCE_UNAVAILABLE`
(ручной маршрут), решение о нём принимает маршрут.
"""

from __future__ import annotations

from app.modules.decisioning.reasons import make
from app.modules.decisioning.types import (
    DecisionInput,
    Features,
    Mode,
    Product,
    ReasonCode,
    SourceMeta,
    SourceStatus,
    SubjectRole,
)

_GAP = (SourceStatus.UNAVAILABLE, SourceStatus.NOT_REQUESTED)


def check_eligibility(inp: DecisionInput) -> ReasonCode | None:
    """Самозанятый (ЕГРИП `404` и НПД `true`) — не клиент кредита для бизнеса."""
    if not inp.policy.eligibility.self_employed.enabled:
        return None
    snap = inp.snapshot
    if snap.registry.meta.status == SourceStatus.NOT_FOUND and snap.npd.is_self_employed:
        return make("SELF_EMPLOYED")
    return None


def check_completeness(inp: DecisionInput, feats: Features) -> tuple[ReasonCode, ...]:
    """`DATA_INCOMPLETE` (поля, согласия) и `REVENUE_UNKNOWN` (нет ни одного источника выручки)."""
    app = inp.application
    out: list[ReasonCode] = []
    missing = list(app.missing_fields)
    if app.amount_rub <= 0:
        missing.append("amount_rub")
    if app.term_months <= 0:
        missing.append("term_months")
    if inp.snapshot.registry.meta.status == SourceStatus.NOT_FOUND:
        missing.append("registry_record")
    if missing or app.unsigned_consents:
        out.append(
            make(
                "DATA_INCOMPLETE",
                fields=", ".join(missing),
                consents=", ".join(app.unsigned_consents),
                todo=", ".join([*missing, *(f"согласие: {c}" for c in app.unsigned_consents)]),
            )
        )
    if feats.revenue_cautious_rub is None:
        out.append(make("REVENUE_UNKNOWN", checked="обороты банка, отчётность, выписка клиента"))
    return tuple(out)


def unavailable_sources(inp: DecisionInput) -> tuple[ReasonCode, ...]:
    """Обязательные источники, которые не ответили (30-04): флаг `SOURCE_UNAVAILABLE`."""
    snap = inp.snapshot
    decision = inp.context.mode == Mode.DECISION
    required: list[tuple[str, SourceMeta]] = [
        ("registry", snap.registry.meta),
        ("tax", snap.tax.meta),
        ("bank_core", snap.customer.meta),
    ]
    if decision:
        required.append(("compliance", snap.compliance.meta))
    required.extend((f"efrsb:{c.role.value}", c.meta) for c in snap.bankruptcies)
    if decision:
        company = [s for s in snap.bki if s.role == SubjectRole.COMPANY]
        if not company:
            required.append(("bki:COMPANY", SourceMeta(SourceStatus.NOT_REQUESTED)))
        required.extend((f"bki:{s.role.value}", s.meta) for s in snap.bki)
    if inp.application.product == Product.CONTRACT:
        required.append(("eis", snap.contracts.meta))
    names = [name for name, meta in required if meta.status in _GAP]
    if not names:
        return ()
    return (make("SOURCE_UNAVAILABLE", sources=", ".join(names)),)
