"""Банковская карточка; клиентская модель не содержит этих полей (50-07)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, PlainSerializer

from app.modules.backoffice.info_schemas import BankClientTask
from app.modules.backoffice.schemas import BankCompany, BankReason, BankRecommendation, Camel

Number = Annotated[
    Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
]


class BankPolicyReference(Camel):
    id: UUID
    version: int
    content_hash: str


class BankFactor(Camel):
    code: str
    title: str
    value: str
    points: int
    max_points: int


class BankMetric(Camel):
    code: str
    title: str
    value: Number | None
    threshold: Number | None
    comparison: Literal["MIN", "MAX"]
    passed: bool | None = Field(description="null — нет значения или порога в сохранённой политике")


class BankRatePart(Camel):
    code: str
    title: str
    percent: Number


class BankRate(Camel):
    rate_percent: Number | None
    raw_rate_percent: Number | None
    corridor_min_percent: Number | None
    corridor_max_percent: Number | None
    rate_with_collateral_percent: Number | None
    parts: list[BankRatePart]


class BankVariant(Camel):
    kind: str
    product_code: str
    amount_rub: int
    term_months: int
    rate_percent: Number
    payment_rub: int
    dscr: Number | None
    stress_dscr: Number | None
    security_required: bool
    recommended: bool
    note: str
    requirements: list[str]


class BankDecisionReason(BankReason):
    kind: str
    params: dict[str, Any]


class BankComparison(Camel):
    code: str
    a_rub: int
    b_rub: int
    deviation_percent: Number
    year: int | None


class BankDecisionSummary(Camel):
    id: UUID
    source: str
    outcome: str
    route: str
    required_level: str
    created_at: datetime
    engine_version: str
    policy: BankPolicyReference
    overrides_decision_id: UUID | None
    override_reason: str | None = Field(description="Внутреннее пояснение, только банку")


class BankDecision(BankDecisionSummary):
    inputs_hash: str
    snapshot_ids: list[UUID]
    recommendation: BankRecommendation | None
    reasons: list[BankDecisionReason]
    manual_reasons: list[BankReason]
    score: int | None
    grade: str | None
    pd_percent: Number | None
    factors: list[BankFactor]
    comparisons: list[BankComparison]
    revenue_monthly_rub: int | None
    free_cash_flow_rub: int | None
    existing_payments_rub: int | None
    payment_rub: int | None
    last_payment_rub: int | None
    overpayment_rub: int | None
    stress_shock_percent: Number | None
    max_amount_rub: int | None
    checks: list[BankMetric]
    rate: BankRate
    flags: list[str]
    features: dict[str, Any] | None
    variants: list[BankVariant]
    trace: list[dict[str, Any]]
    assessed_input: dict[str, Any]


class BankSourceSnapshot(Camel):
    id: UUID
    run_id: UUID
    system: str
    resource: str
    subject_inn: str
    status: str
    data_actual_at: date | None
    retrieved_at: datetime
    request_id: str | None
    payload_hash: str
    payload: dict[str, Any] | list[Any]
    used_by_current_decision: bool


class BankHistoryEvent(Camel):
    id: int
    at: datetime
    kind: str
    from_status: str | None
    to_status: str | None
    step_code: str | None
    actor_type: str
    actor_id: UUID | None
    actor_name: str | None
    reason_code: str | None
    payload: dict[str, Any]
    request_id: str | None


class BankApplicant(BankCompany):
    registered_on: date | None
    status: str | None
    okved: str | None


class BankSubmittedBy(Camel):
    id: UUID
    name: str
    company_role: str | None


class BankApplicationCard(Camel):
    id: UUID
    number: str
    status: str
    version: int
    stale: bool = Field(description="expectedVersion отличается от версии согласованного ответа")
    current_version_id: UUID | None
    product_code: str | None
    amount_rub: int | None
    term_months: int | None
    purpose_code: str | None
    draft: dict[str, Any]
    company: BankApplicant
    submitted_by: BankSubmittedBy
    submitted_at: datetime | None
    decision: BankDecision | None
    engine_decision_id: UUID | None
    engine_recommendation: BankRecommendation | None
    decisions: list[BankDecisionSummary]
    source_snapshots: list[BankSourceSnapshot]
    history: list[BankHistoryEvent]
    documents: list[dict[str, Any]] | None = Field(description="null — сервис T-332 не подключён")
    client_tasks: list[BankClientTask] = Field(default_factory=list)
    latest_answered_round: int | None = Field(
        default=None, description="Последний отправленный клиентом раунд, не черновик"
    )
