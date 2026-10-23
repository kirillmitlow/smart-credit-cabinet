"""Проверка ручного решения андеррайтера (30-11, D-086, T-362, T-364).

Чистая функция без базы, сети и часов. Расчёт тот же, что у автомата (`affordability.evaluate`,
`check_product`, `pricing.corridor`): платёж, DSCR и стресс пересчитываются по введённым
условиям и признакам ENGINE-решения. Все пороги берутся из `policy.underwriter`, `policy.affordability`
и `policy.routing.authority`; своих чисел здесь нет.

Правила:
- исходы: `APPROVED`, `COUNTER_OFFER`, `REJECTED`; ядро должно было отдать `MANUAL_REVIEW`;
- `APPROVED` только на запрошенные продукт, сумму и срок (иначе — встречное);
- жёсткие запреты не снимает никто: коридор ставки, границы каталога и правила продукта,
  потолки продукта и долг к выручке; стоп-факторов в ручном маршруте нет;
- исключение из политики (DSCR или стресс ниже порогов автомата, но не ниже порогов исключения,
  либо одобрение вопреки рекомендации «отказать») — всегда `L2`, код и комментарий строгой длины;
- уровень по матрице полномочий считается от суммы условий (для отказа — от запрошенной суммы).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.modules.decisioning import affordability, pricing
from app.modules.decisioning import loan_math as lm
from app.modules.decisioning.decide import product_context
from app.modules.decisioning.products import authority_level, check_product
from app.modules.decisioning.serialization import inputs_hash, policy_hash
from app.modules.decisioning.types import (
    DecisionInput,
    DecisionResult,
    Level,
    Outcome,
    ParamValue,
    Product,
)

ALLOWED_OUTCOMES = (Outcome.APPROVED, Outcome.COUNTER_OFFER, Outcome.REJECTED)
_WAIVABLE = frozenset({"DSCR_LOW", "STRESS_DSCR_LOW"})
_RANK = {Level.L0: 0, Level.L1: 1, Level.L2: 2}


class ViolationKind(StrEnum):
    INPUT = "INPUT"  # некорректный запрос или устаревший снимок ядра
    HARD = "HARD"  # жёсткий запрет, не снимается ни одним уровнем
    AUTHORITY = "AUTHORITY"  # хватает прав у более высокого уровня (403)
    REASON = "REASON"  # не хватает причины или комментария


@dataclass(frozen=True, slots=True)
class UnderwriterTerms:
    """Условия решения. `rate` — доля (0,215); `None` — ставка расчёта по грейду и залогу."""

    product: Product
    amount_rub: int
    term_months: int
    rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class UwViolation:
    code: str
    kind: ViolationKind
    params: dict[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UwCheck:
    """Одна проверенная условие: код и результат."""

    code: str
    passed: bool


@dataclass(frozen=True, slots=True)
class UnderwriterEvaluation:
    allowed: bool
    outcome: Outcome
    terms: UnderwriterTerms | None  # со ставкой, подставленной по умолчанию
    baseline_outcome: Outcome | None  # рекомендация ядра
    deviation: bool
    exception_used: bool
    exception_codes: tuple[str, ...]
    required_level: Level
    actor_level: Level
    rate: Decimal | None
    rate_corridor_min: Decimal | None
    rate_corridor_max: Decimal | None
    payment_rub: int | None
    last_payment_rub: int | None
    overpayment_rub: int | None
    dscr: Decimal | None
    stress_dscr: Decimal | None
    debt_to_revenue_with_new: Decimal | None
    min_comment_chars: int
    reason_code: str | None
    violations: tuple[UwViolation, ...]
    checks: tuple[UwCheck, ...]
    inputs_hash: str
    policy_version: int
    policy_hash: str
    application_version: int | None

    @property
    def violation_codes(self) -> tuple[str, ...]:
        return tuple(v.code for v in self.violations)


def _rejected_early(  # noqa: PLR0913 — вход проверки не прошёл: числа не считаем
    inp: DecisionInput,
    engine: DecisionResult,
    outcome: Outcome,
    actor: Level,
    reason_code: str | None,
    version: int | None,
    violations: list[UwViolation],
) -> UnderwriterEvaluation:
    return UnderwriterEvaluation(
        allowed=False,
        outcome=outcome,
        terms=None,
        baseline_outcome=engine.recommendation.outcome if engine.recommendation else None,
        deviation=False,
        exception_used=False,
        exception_codes=(),
        required_level=engine.required_level,
        actor_level=actor,
        rate=None,
        rate_corridor_min=None,
        rate_corridor_max=None,
        payment_rub=None,
        last_payment_rub=None,
        overpayment_rub=None,
        dscr=None,
        stress_dscr=None,
        debt_to_revenue_with_new=None,
        min_comment_chars=0,
        reason_code=reason_code,
        violations=tuple(violations),
        checks=(),
        inputs_hash=engine.inputs_hash,
        policy_version=inp.policy.meta.version,
        policy_hash=engine.policy_hash,
        application_version=version,
    )


def evaluate_underwriter_decision(  # noqa: PLR0912, PLR0913, PLR0914, PLR0915 — один проход по правилам 30-11
    inputs: DecisionInput,
    engine_result: DecisionResult,
    outcome: Outcome,
    terms: UnderwriterTerms | None,
    actor_level: Level,
    reason_code: str | None,
    comment: str | None,
    *,
    application_version: int | None = None,
) -> UnderwriterEvaluation:
    """Допустимо ли решение андеррайтера; возвращает пересчёт и все нарушения с кодами."""
    policy = inputs.policy
    uw = policy.underwriter
    app = inputs.application
    feats = engine_result.features
    grade = engine_result.numbers.grade
    fatal: list[UwViolation] = []

    if outcome not in ALLOWED_OUTCOMES:
        fatal.append(UwViolation("OUTCOME_NOT_ALLOWED", ViolationKind.INPUT))
    if actor_level not in (Level.L1, Level.L2):
        fatal.append(UwViolation("ACTOR_LEVEL_INVALID", ViolationKind.INPUT))
    if engine_result.outcome != Outcome.MANUAL_REVIEW or feats is None or grade is None:
        fatal.append(UwViolation("ENGINE_NOT_MANUAL_REVIEW", ViolationKind.INPUT))
    elif (
        inputs_hash(inputs) != engine_result.inputs_hash
        or policy_hash(policy) != engine_result.policy_hash
    ):
        fatal.append(UwViolation("ENGINE_RESULT_MISMATCH", ViolationKind.INPUT))
    if outcome == Outcome.REJECTED and terms is not None:
        fatal.append(UwViolation("TERMS_NOT_ALLOWED", ViolationKind.INPUT))
    if fatal or feats is None or grade is None:
        return _rejected_early(
            inputs, engine_result, outcome, actor_level, reason_code, application_version, fatal
        )

    violations: list[UwViolation] = []
    checks: list[UwCheck] = []

    def check(code: str, passed: bool) -> None:  # noqa: FBT001
        checks.append(UwCheck(code, passed))

    baseline = engine_result.recommendation.outcome if engine_result.recommendation else None
    resolved: UnderwriterTerms | None = None
    rate: Decimal | None = None
    low = high = None
    pay = last = over = None
    d = s = None
    debt_ratio: Decimal | None = None
    waived: list[str] = []
    exception = False

    if outcome != Outcome.REJECTED:
        if terms is None:
            violations.append(UwViolation("TERMS_REQUIRED", ViolationKind.INPUT))
        else:
            same = (
                terms.product == app.product
                and terms.amount_rub == app.amount_rub
                and terms.term_months == app.term_months
            )
            if outcome == Outcome.APPROVED and not same:
                violations.append(UwViolation("APPROVED_TERMS_DIFFER", ViolationKind.INPUT))
            if outcome == Outcome.COUNTER_OFFER and same:
                violations.append(UwViolation("COUNTER_SAME_AS_REQUEST", ViolationKind.INPUT))
            rate = (
                terms.rate
                if terms.rate is not None
                else pricing.rate_for(policy, terms.product, grade, feats.collateral_provided).rate
            )
            resolved = UnderwriterTerms(terms.product, terms.amount_rub, terms.term_months, rate)
            low, high = pricing.corridor(policy, terms.product)
            in_corridor = low <= rate <= high
            check("RATE_IN_CORRIDOR", in_corridor)
            if not in_corridor:
                violations.append(
                    UwViolation(
                        "RATE_OUT_OF_CORRIDOR",
                        ViolationKind.HARD,
                        {"rate": rate, "corridor_min": low, "corridor_max": high},
                    )
                )
            contract = next(
                (
                    c
                    for c in inputs.snapshot.contracts.contracts
                    if c.registry_number == app.contract_registry_number
                ),
                None,
            )
            pctx = product_context(inputs, feats, grade)
            product_bad = check_product(
                policy, terms.product, terms.amount_rub, terms.term_months, pctx
            )
            check("PRODUCT_RULES", not product_bad)
            for r in product_bad:
                violations.append(UwViolation(r.code, ViolationKind.HARD, dict(r.params)))
            afford = affordability.evaluate(
                policy,
                terms.product,
                terms.amount_rub,
                terms.term_months,
                rate,
                feats,
                app,
                contract,
                feats.inflow_average_rub,
                inputs.context.p_def12,
            )
            pay, last, over = afford.payment_rub, afford.last_payment_rub, afford.overpayment_rub
            debt_ratio = afford.debt_ratio_with_new
            if pay > 0:
                flow = feats.flow_model_rub or 0
                exact_d = lm.dscr(flow, feats.existing_payments_rub, pay)
                exact_s = lm.stress_dscr(flow, feats.existing_payments_rub, pay, feats.stress_shock)
                d, s = afford.dscr, afford.stress_dscr
                dscr_low = exact_d < policy.affordability.dscr_min.value
                stress_low = exact_s < policy.affordability.stress_dscr_min.value
                check("DSCR_MIN", not dscr_low)
                check("STRESS_DSCR_MIN", not stress_low)
                if dscr_low:
                    waived.append("DSCR_LOW")
                if stress_low:
                    waived.append("STRESS_DSCR_LOW")
                floor_d_ok = exact_d >= uw.exception_dscr_min.value
                floor_s_ok = exact_s >= uw.exception_stress_min.value
                if waived:
                    check("EXCEPTION_FLOOR_DSCR", floor_d_ok)
                    check("EXCEPTION_FLOOR_STRESS", floor_s_ok)
                if not floor_d_ok:
                    violations.append(
                        UwViolation(
                            "DSCR_BELOW_EXCEPTION_FLOOR",
                            ViolationKind.HARD,
                            {"dscr": afford.dscr, "floor": uw.exception_dscr_min.value},
                        )
                    )
                if not floor_s_ok:
                    violations.append(
                        UwViolation(
                            "STRESS_BELOW_EXCEPTION_FLOOR",
                            ViolationKind.HARD,
                            {
                                "stress_dscr": afford.stress_dscr,
                                "floor": uw.exception_stress_min.value,
                            },
                        )
                    )
            for r in afford.violations:
                if r.code in _WAIVABLE and r.params.get("source") != "P_DEF12":
                    continue  # пороги исключения проверены выше по точным числам
                violations.append(UwViolation(r.code, ViolationKind.HARD, dict(r.params)))
            check(
                "DEBT_AND_CAPS",
                not any(r.code in ("DEBT_TOO_HIGH", "LIMIT_ABOVE_CAP") for r in afford.violations),
            )
            exception = bool(waived)
    if baseline == Outcome.REJECTED and outcome != Outcome.REJECTED:
        exception = True  # одобрить то, что ядро отвергало: «мягче»

    # Уровень: условия решения по матрице; исключение — всегда L2
    if outcome == Outcome.REJECTED:
        required = engine_result.required_level
    else:
        amount = resolved.amount_rub if resolved else app.amount_rub
        required = authority_level(policy, amount, grade)
    if exception:
        required = Level.L2
    authority_ok = _RANK[actor_level] >= _RANK[required]
    check("AUTHORITY", authority_ok)
    if not authority_ok:
        violations.append(
            UwViolation(
                "AUTHORITY_LEVEL_TOO_LOW",
                ViolationKind.AUTHORITY,
                {"required_level": required.value, "actor_level": actor_level.value},
            )
        )

    # Причина и комментарий: нужны при любом отклонении от рекомендации ядра
    deviation = exception or baseline is None or outcome != baseline
    text = (comment or "").strip()
    strict = exception or required == Level.L2 or reason_code == "UW_OTHER"
    min_chars = (
        (uw.comment_min_chars_strict.value if strict else uw.comment_min_chars.value)
        if deviation
        else 0
    )
    if reason_code is not None and reason_code not in uw.reason_codes.value:
        violations.append(
            UwViolation("REASON_UNKNOWN", ViolationKind.REASON, {"code": reason_code})
        )
    elif deviation and reason_code is None:
        violations.append(UwViolation("REASON_REQUIRED", ViolationKind.REASON))
    if deviation and len(text) < min_chars:
        violations.append(
            UwViolation(
                "COMMENT_TOO_SHORT",
                ViolationKind.REASON,
                {"min_chars": min_chars, "actual_chars": len(text)},
            )
        )
    check("REASON_AND_COMMENT", not any(v.kind == ViolationKind.REASON for v in violations))

    return UnderwriterEvaluation(
        allowed=not violations,
        outcome=outcome,
        terms=resolved,
        baseline_outcome=baseline,
        deviation=deviation,
        exception_used=exception,
        exception_codes=tuple(waived),
        required_level=required,
        actor_level=actor_level,
        rate=rate,
        rate_corridor_min=low,
        rate_corridor_max=high,
        payment_rub=pay,
        last_payment_rub=last,
        overpayment_rub=over,
        dscr=d,
        stress_dscr=s,
        debt_to_revenue_with_new=debt_ratio,
        min_comment_chars=min_chars,
        reason_code=reason_code,
        violations=tuple(violations),
        checks=tuple(checks),
        inputs_hash=engine_result.inputs_hash,
        policy_version=inputs.policy.meta.version,
        policy_hash=engine_result.policy_hash,
        application_version=application_version,
    )
