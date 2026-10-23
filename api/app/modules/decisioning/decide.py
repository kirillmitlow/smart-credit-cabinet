"""Сборка `decide()` из шагов (T-300, 30-01): единственная точка входа ядра.

Чистая функция: без сети, базы, часов и случайности. Одинаковый вход даёт одинаковый выход,
включая порядок причин. Порядок шагов: допуск → признаки → стоп-факторы → полнота данных →
скоринг → ставка → лимиты и правила продукта → маршрут → встречные → объяснения.
Приоритет исхода: стоп-фактор → `NEEDS_INFO` → условное встречное молодому бизнесу → ручные
триггеры → автоматическое решение.
"""

from __future__ import annotations

from app.modules.decisioning import affordability, counter_offers, pricing
from app.modules.decisioning.eligibility import (
    check_completeness,
    check_eligibility,
    unavailable_sources,
)
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.flags import evaluate_flags
from app.modules.decisioning.products import ProductContext, auto_limit, check_product
from app.modules.decisioning.reasons import order_reasons
from app.modules.decisioning.routing import route
from app.modules.decisioning.scoring import score
from app.modules.decisioning.serialization import inputs_hash, policy_hash
from app.modules.decisioning.stops import evaluate_stop_factors
from app.modules.decisioning.texts_ru import render
from app.modules.decisioning.types import (
    ContractInfo,
    DecisionInput,
    DecisionResult,
    Features,
    Grade,
    Level,
    Numbers,
    Outcome,
    ReasonCode,
    Recommendation,
    Route,
    TraceStep,
    Variant,
)


def _contract(inp: DecisionInput) -> ContractInfo | None:
    number = inp.application.contract_registry_number
    for c in inp.snapshot.contracts.contracts:
        if c.registry_number == number:
            return c
    return None


def product_context(inp: DecisionInput, feats: Features, grade: Grade | None) -> ProductContext:
    """Контекст правил продукта: общий для `decide` и ручного решения андеррайтера."""
    return ProductContext(
        app_today=inp.context.app_today,
        business_age_months=feats.business_age_months,
        registration_date=inp.snapshot.registry.registration_date,
        is_bank_customer=feats.is_bank_customer,
        customer_turnover_months=len(inp.snapshot.turnover.months),
        collateral_provided=feats.collateral_provided,
        security_confirmed=feats.security_confirmed,
        grade=grade,
        contract=_contract(inp),
    )


def _skipped(step: str, why: str) -> TraceStep:
    return TraceStep(step, False, {"reason": why})


class _Builder:
    """Собирает неизменяемый результат: общие поля, объяснения, хеши."""

    def __init__(self, inp: DecisionInput) -> None:
        self.inp = inp
        self.trace: list[TraceStep] = []
        self.hash = inputs_hash(inp)
        self.policy_hash = policy_hash(inp.policy)

    def finish(
        self,
        *,
        outcome: Outcome,
        reasons: tuple[ReasonCode, ...],
        features: Features | None,
        numbers: Numbers,
        route_kind: Route = Route.AUTO,
        level: Level = Level.L0,
        variants: tuple[Variant, ...] = (),
        variants_status: str = "NOT_APPLICABLE",
        recommendation: Recommendation | None = None,
    ) -> DecisionResult:
        reasons = order_reasons(reasons)
        explanations = tuple(render(r) for r in reasons)
        self.trace.append(TraceStep("13.explanations", True, {"texts": len(explanations)}))
        return DecisionResult(
            outcome=outcome,
            route=route_kind,
            required_level=level,
            reasons=reasons,
            numbers=numbers,
            features=features,
            variants=variants,
            variants_status=variants_status,
            recommendation=recommendation,
            explanations=explanations,
            trace=tuple(self.trace),
            inputs_hash=self.hash,
            policy_version=self.inp.policy.meta.version,
            policy_hash=self.policy_hash,
            mode=self.inp.context.mode,
        )


def _feature_numbers(feats: Features) -> Numbers:
    return Numbers(
        revenue_cautious_rub=feats.revenue_cautious_rub,
        revenue_annual_rub=feats.revenue_annual_rub,
        flow_rub=feats.flow_model_rub,
        existing_payments_rub=feats.existing_payments_rub,
        stress_shock=feats.stress_shock,
    )


def decide(inputs: DecisionInput) -> DecisionResult:
    """Детерминированная функция: одинаковые входы — одинаковый результат (INV-50, INV-51)."""
    inp = inputs
    policy = inp.policy
    app = inp.application
    b = _Builder(inp)

    # Шаг 1. Допуск: самозанятый не клиент кредита, остальные источники не нужны
    self_employed = check_eligibility(inp)
    b.trace.append(TraceStep("1.eligibility", True, {"self_employed": self_employed is not None}))
    if self_employed is not None:
        b.trace.append(_skipped("5.stop_factors", "NOT_ELIGIBLE"))
        return b.finish(
            outcome=Outcome.NOT_ELIGIBLE,
            reasons=(self_employed,),
            features=None,
            numbers=Numbers(),
        )

    # Шаг 6 (раньше стопов: налоговому стопу нужна выручка). Признаки считаются всегда
    feats = compute_features(inp)
    b.trace.append(
        TraceStep(
            "6.features",
            True,
            {
                "revenue_source": feats.revenue_source,
                "revenue_cautious_rub": feats.revenue_cautious_rub,
                "flow_model_rub": feats.flow_model_rub,
                "credit_history_class": feats.credit_history_class,
            },
        )
    )
    base_numbers = _feature_numbers(feats)

    # Шаг 5. Все стоп-факторы; недоступный источник не отменяет найденный по другим данным
    stops = evaluate_stop_factors(inp, feats)
    b.trace.append(
        TraceStep("5.stop_factors", True, {"triggered": ",".join(r.code for r in stops)})
    )
    if stops:
        for step in ("7.scoring", "8.pricing", "9.limits", "10.product_rules", "11.routing"):
            b.trace.append(_skipped(step, "STOP_FACTOR"))
        return b.finish(
            outcome=Outcome.REJECTED, reasons=stops, features=feats, numbers=base_numbers
        )

    # Шаг 3а. Полнота данных и достаточность выручки: нехватка — вопрос клиенту, а не отказ
    needs = check_completeness(inp, feats)
    b.trace.append(TraceStep("3a.completeness", True, {"missing": ",".join(r.code for r in needs)}))
    if needs:
        for step in ("7.scoring", "8.pricing", "9.limits", "10.product_rules", "11.routing"):
            b.trace.append(_skipped(step, "NEEDS_INFO"))
        return b.finish(
            outcome=Outcome.NEEDS_INFO, reasons=needs, features=feats, numbers=base_numbers
        )

    # Шаг 7. Скоринг
    result = score(feats, policy, inp.context.mode)
    b.trace.append(
        TraceStep(
            "7.scoring",
            True,
            {
                "points": result.points,
                "grade": result.grade.value,
                "pd": result.pd,
                "capped": result.capped is not None,
                "cautious_bki": inp.context.mode.value == "PREVIEW" or not feats.bki_known,
            },
        )
    )

    # Шаг 8. Ставка: до лимитов, от суммы не зависит (D-084)
    breakdown = pricing.rate_for(policy, app.product, result.grade, feats.collateral_provided)
    b.trace.append(
        TraceStep("8.pricing", True, {"rate": breakdown.rate, "raw": breakdown.raw_rate})
    )

    # Шаги 9–10 независимы: собираем все нарушения, не останавливаясь на первом
    contract = _contract(inp)
    afford = affordability.evaluate(
        policy,
        app.product,
        app.amount_rub,
        app.term_months,
        breakdown.rate,
        feats,
        app,
        contract,
        feats.inflow_average_rub,
        inp.context.p_def12,
    )
    b.trace.append(
        TraceStep(
            "9.limits",
            True,
            {
                "dscr": afford.dscr,
                "stress_dscr": afford.stress_dscr,
                "debt_ratio_with_new": afford.debt_ratio_with_new,
                "violations": ",".join(r.code for r in afford.violations),
                "near_threshold": ",".join(
                    str(r.params.get("metric")) for r in afford.near_threshold
                ),
                "p_def12": (
                    "SKIPPED_NOT_PROVIDED"
                    if inp.context.p_def12 is None
                    else format(inp.context.p_def12, "f")
                ),
            },
        )
    )
    product_ctx = product_context(inp, feats, result.grade)
    product_violations = check_product(
        policy, app.product, app.amount_rub, app.term_months, product_ctx
    )
    b.trace.append(
        TraceStep(
            "10.product_rules", True, {"violations": ",".join(r.code for r in product_violations)}
        )
    )

    # Шаги 11–12. Встречные нужны, только если запрос не проходит; для грейда E маршрут их не смотрит
    flags = evaluate_flags(inp, feats) + unavailable_sources(inp)
    hard = bool(afford.violations or product_violations)
    if hard and result.grade != Grade.E:
        search = counter_offers.search_counter_offers(
            policy,
            app,
            breakdown.rate,
            feats,
            grade=result.grade,
            product_ctx=product_ctx,
            contract=contract,
            inflow_average=feats.inflow_average_rub,
            request=afford,
        )
    else:
        search = counter_offers.NOT_SEARCHED
    routed = route(
        policy, app, feats, result, afford, breakdown.rate, product_violations, flags, search
    )
    b.trace.append(
        TraceStep(
            "11.routing",
            True,
            {
                "outcome": routed.outcome.value,
                "route": routed.route.value,
                "level": routed.level.value,
                "manual": ",".join(r.code for r in routed.manual_reasons),
            },
        )
    )
    b.trace.append(
        TraceStep(
            "12.counter_offers",
            routed.outcome == Outcome.COUNTER_OFFER or routed.recommendation is not None,
            {
                "status": routed.variants_status,
                "feasible": search.feasible,
                "cards": len(routed.variants),
            },
        )
    )

    numbers = Numbers(
        revenue_cautious_rub=feats.revenue_cautious_rub,
        revenue_annual_rub=feats.revenue_annual_rub,
        flow_rub=feats.flow_model_rub,
        existing_payments_rub=feats.existing_payments_rub,
        score_points=result.points,
        grade=result.grade,
        pd=result.pd,
        factors=result.factors,
        rate=breakdown.rate,
        rate_breakdown=breakdown,
        payment_rub=afford.payment_rub,
        last_payment_rub=afford.last_payment_rub,
        overpayment_rub=afford.overpayment_rub,
        dscr=afford.dscr,
        stress_dscr=afford.stress_dscr,
        stress_shock=afford.shock,
        debt_to_revenue_with_new=afford.debt_ratio_with_new,
        p_max_rub=afford.p_max_rub,
        max_amount_formula_rub=afford.max_amount_formula_rub,
        max_amount_rub=afford.max_amount_rub,
        max_amount_by_term=afford.max_amount_by_term,
        min_term_months=afford.min_term_months,
        auto_limit_rub=_auto_limit(inp, result.grade),
        p_def12=inp.context.p_def12,
    )
    return b.finish(
        outcome=routed.outcome,
        reasons=routed.reasons,
        features=feats,
        numbers=numbers,
        route_kind=routed.route,
        level=routed.level,
        variants=routed.variants,
        variants_status=routed.variants_status,
        recommendation=routed.recommendation,
    )


def _auto_limit(inp: DecisionInput, grade: Grade) -> int | None:
    if grade in (Grade.C, Grade.D, Grade.E):
        return None
    return auto_limit(inp.policy, inp.application.product, grade)
