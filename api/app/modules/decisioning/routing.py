"""Маршрут (T-296, шаг 11, 30-11): автомат или человек, серые зоны, матрица полномочий.

Принцип D-034: автомат одобряет, когда всё хорошо и в пределах полномочий, и отказывает, только
когда уверен. Всё сомнительное идёт человеку. Стопы и допуск обработаны выше (`decide`).

Порядок таблицы маршрута 30-11 (сверху вниз): условное встречное молодому бизнесу → ручные
причины → грейд E или нет встречных → одобрение → встречные.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.decisioning.affordability import Affordability
from app.modules.decisioning.counter_offers import CounterOfferSearch, conditional_security_variant
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.products import authority_level, auto_limit
from app.modules.decisioning.reasons import make, order_reasons
from app.modules.decisioning.scoring import ScoreResult
from app.modules.decisioning.texts_ru import top_deficit_phrases
from app.modules.decisioning.types import (
    Application,
    Features,
    Grade,
    Level,
    Outcome,
    Product,
    ReasonCode,
    Recommendation,
    Route,
    Variant,
)


@dataclass(frozen=True, slots=True)
class RouteResult:
    outcome: Outcome
    route: Route
    level: Level
    reasons: tuple[ReasonCode, ...]
    recommendation: Recommendation | None
    variants: tuple[Variant, ...]
    variants_status: str
    manual_reasons: tuple[ReasonCode, ...]


def _points_gray(policy: Policy, score: ScoreResult) -> ReasonCode | None:
    gray = policy.routing.gray
    in_b = score.grade == Grade.B and gray.points_b_low <= score.points <= gray.points_b_high
    in_e = score.grade == Grade.E and gray.points_e_low <= score.points <= gray.points_e_high
    if in_b or in_e:
        return make(
            "NEAR_THRESHOLD",
            metric="SCORE",
            value=Decimal(score.points),
            zone_from=Decimal(gray.points_b_low if in_b else gray.points_e_low),
            zone_to=Decimal(gray.points_b_high if in_b else gray.points_e_high),
        )
    return None


def _collateral_review(policy: Policy, app: Application) -> bool:
    """Залог есть в заявке или обязателен для продукта: стоимость и документы смотрит человек."""
    threshold = policy.product_config(app.product.value).collateral_required_above_rub
    required = threshold is not None and app.amount_rub > threshold
    return app.collateral is not None or required


def _hint(app: Application, young_with_security: bool, base: Outcome) -> str:
    if app.product == Product.INVESTMENT:
        return "REQUEST_SELLER_DOCUMENT"
    if young_with_security:
        return "APPROVE_WITH_GUARANTEE" if app.guarantor is not None else "APPROVE_WITH_COLLATERAL"
    return "APPROVE" if base == Outcome.APPROVED else ""


def route(  # noqa: PLR0913, PLR0914 — сборка исхода по таблице маршрута
    policy: Policy,
    app: Application,
    feats: Features,
    score: ScoreResult,
    afford: Affordability,
    rate: Decimal,
    product_violations: tuple[ReasonCode, ...],
    flags: tuple[ReasonCode, ...],
    search: CounterOfferSearch,
) -> RouteResult:
    young_limit = policy.restrictions.business_too_young.value
    age = feats.business_age_months
    young = age is not None and age < young_limit
    constraint: list[ReasonCode] = []
    if young:
        constraint.append(
            make(
                "BUSINESS_TOO_YOUNG",
                age_months=age,
                required_months=young_limit,
                security="есть" if feats.security_confirmed else "нет",
            )
        )
    grade = score.grade
    info = [score.capped] if score.capped is not None else []
    violations = afford.violations + product_violations
    hard = bool(violations)
    # Грейд E отказывается одной причиной RISK_TOO_HIGH: GRADE_NOT_ALLOWED по каждому продукту — шум
    shown = () if grade == Grade.E else violations

    # Строка 3: молодой бизнес без обеспечения и без флагов → условное встречное
    if young and not feats.security_confirmed and not flags and not hard:
        variant = conditional_security_variant(app, rate, afford)
        reasons = order_reasons([*constraint, *info])
        return RouteResult(
            outcome=Outcome.COUNTER_OFFER,
            route=Route.AUTO,
            level=Level.L0,
            reasons=reasons,
            recommendation=None,
            variants=(variant,),
            variants_status="CONDITIONAL_ONLY",
            manual_reasons=(),
        )

    # Что решило бы ядро без ручных триггеров (строки 5–7)
    if grade == Grade.E:
        base = Outcome.REJECTED
        out_reason = [
            make("RISK_TOO_HIGH", points=score.points, factors=top_deficit_phrases(score))
        ]
    elif hard:
        if search.feasible:
            base, out_reason = Outcome.COUNTER_OFFER, []
        else:
            base = Outcome.REJECTED
            out_reason = [make("NO_OFFER_FOUND", **search.probe)]
    else:
        base, out_reason = Outcome.APPROVED, []

    # Ручные причины (строка 4)
    manual: list[ReasonCode] = list(flags)
    young_with_security = young and feats.security_confirmed
    if grade in (Grade.C, Grade.D):
        manual.append(
            make("GRADE_NEEDS_REVIEW", grade=grade.value, points=score.points, pd=score.pd)
        )
    if not hard and grade in (Grade.A, Grade.B):
        limit = auto_limit(policy, app.product, grade)
        if limit is not None and app.amount_rub > limit:
            manual.append(
                make(
                    "AMOUNT_ABOVE_AUTO_LIMIT",
                    amount_rub=app.amount_rub,
                    limit_rub=limit,
                    grade=grade.value,
                )
            )
    if _collateral_review(policy, app):
        collateral = app.collateral
        manual.append(
            make(
                "COLLATERAL_REVIEW",
                description=collateral.description if collateral else "обязателен для продукта",
                value_rub=collateral.value_rub if collateral else None,
                share=(
                    Decimal(app.amount_rub) / Decimal(collateral.value_rub)
                    if collateral and collateral.value_rub
                    else None
                ),
            )
        )
    gray_points = _points_gray(policy, score)
    if gray_points is not None:
        manual.append(gray_points)
    if not hard:
        manual.extend(afford.near_threshold)

    if young_with_security:
        manual.append(constraint[0])

    if manual:
        # Ручной маршрут: все причины сразу, у решения есть рекомендация ядра
        reasons = order_reasons([*flags, *constraint, *shown, *manual, *info])
        return RouteResult(
            outcome=Outcome.MANUAL_REVIEW,
            route=Route.MANUAL,
            level=authority_level(policy, app.amount_rub, grade),
            reasons=reasons,
            recommendation=Recommendation(base, _hint(app, young_with_security, base)),
            variants=(),
            variants_status=search.status,
            manual_reasons=tuple(manual),
        )

    reasons = order_reasons([*constraint, *shown, *out_reason, *info])
    return RouteResult(
        outcome=base,
        route=Route.AUTO,
        level=Level.L0,
        reasons=reasons,
        recommendation=None,
        variants=search.variants,
        variants_status=search.status if base == Outcome.COUNTER_OFFER else "NOT_APPLICABLE",
        manual_reasons=(),
    )
