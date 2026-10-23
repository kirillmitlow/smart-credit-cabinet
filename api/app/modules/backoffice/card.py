"""Проекция сохранённого решения, без нового расчёта кредита и без записи в чужие таблицы."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules import auth
from app.modules.backoffice import queries
from app.modules.backoffice.card_schemas import (
    BankApplicant,
    BankApplicationCard,
    BankDecision,
    BankDecisionReason,
    BankDecisionSummary,
    BankFactor,
    BankHistoryEvent,
    BankMetric,
    BankPolicyReference,
    BankRate,
    BankRatePart,
    BankSourceSnapshot,
    BankSubmittedBy,
    BankVariant,
)
from app.modules.backoffice.schemas import BankRecommendation
from app.modules.backoffice.service import _TITLES, manual_reasons, require_bank
from app.shared import db
from app.shared.errors import not_found

_FACTOR_NAMES = {
    "SC_AGE": "Возраст бизнеса",
    "SC_CREDIT_HISTORY": "Кредитная история",
    "SC_INQUIRIES": "Запросы в БКИ",
    "SC_DEBT_LOAD": "Долговая нагрузка",
    "SC_TREND": "Динамика оборотов",
    "SC_VOLATILITY": "Устойчивость оборотов",
    "SC_TAX": "Налоги",
    "SC_CLIENT": "Обслуживание в банке",
    "SC_COVERAGE": "Покрытие текущих платежей",
}


def _number(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _percent(value: Any) -> Decimal | None:
    number = _number(value)
    return number * 100 if number is not None else None


def summary(row: dict[str, Any]) -> BankDecisionSummary:
    return BankDecisionSummary(
        id=row["id"],
        source=row["source"],
        outcome=row["outcome"],
        route=row["route"],
        required_level=row["required_level"],
        created_at=row["created_at"],
        engine_version=row["engine_version"],
        policy=BankPolicyReference(
            id=row["policy_version_id"],
            version=row["policy_number"],
            content_hash=row["policy_hash"],
        ),
        overrides_decision_id=row["overrides_decision_id"],
        override_reason=row["override_reason"],
    )


def _metric(
    code: str, title: str, value: Any, threshold: Any, *, maximum: bool = False
) -> BankMetric:
    number, bound = _number(value), _number(threshold)
    passed = (
        None if number is None or bound is None else number <= bound if maximum else number >= bound
    )
    return BankMetric(
        code=code,
        title=title,
        value=number,
        threshold=bound,
        comparison="MAX" if maximum else "MIN",
        passed=passed,
    )


def _policy_bound(policy: dict[str, Any], name: str) -> Any:
    return ((policy.get("affordability") or {}).get(name) or {}).get("value")


def decision_view(row: dict[str, Any]) -> BankDecision:
    explain, policy = row["explain"] or {}, row["policy_content"]
    numbers = explain.get("numbers") or {}
    breakdown = numbers.get("rate_breakdown") or {}
    texts = {x["code"]: x.get("underwriter", "") for x in explain.get("explanations") or []}
    reasons = [
        BankDecisionReason(
            code=r["code"],
            kind=r["kind"],
            params=r.get("params") or {},
            title=_TITLES.get(r["code"], "Причина решения"),
            detail=texts.get(r["code"], ""),
        )
        for r in explain.get("reasons") or []
    ]
    factors = sorted(
        (
            BankFactor(
                code=f["factor"],
                title=_FACTOR_NAMES.get(f["factor"], f["factor"]),
                value=f["value"],
                points=f["points"],
                max_points=f["max_points"],
            )
            for f in numbers.get("factors") or []
        ),
        key=lambda f: f.max_points - f.points,
        reverse=True,
    )
    checks = [
        _metric(
            "DSCR", "Покрытие платежей", numbers.get("dscr"), _policy_bound(policy, "dscr_min")
        ),
        _metric(
            "STRESS_DSCR",
            "Стресс-сценарий",
            numbers.get("stress_dscr"),
            _policy_bound(policy, "stress_dscr_min"),
        ),
        _metric(
            "DEBT_TO_REVENUE",
            "Долг к годовой выручке",
            numbers.get("debt_to_revenue_with_new"),
            _policy_bound(policy, "debt_to_revenue_max"),
            maximum=True,
        ),
    ]
    request = row["inputs"].get("application") or {}
    if request.get("product") == "CREDIT_LINE":
        share = _number(_policy_bound(policy, "line_share_of_monthly_revenue"))
        revenue = _number(numbers.get("revenue_cautious_rub"))
        checks.append(
            _metric(
                "LINE_LIMIT",
                "Лимит к месячной выручке",
                request.get("amount_rub"),
                revenue * share if revenue is not None and share is not None else None,
                maximum=True,
            )
        )
    parts = []
    for code, title in (
        ("key_rate", "Ключевая ставка"),
        ("spread", "Базовая маржа"),
        ("expected_loss", "Ожидаемые потери"),
        ("expenses", "Расходы"),
        ("capital_charge", "Плата за капитал"),
    ):
        value = _percent(breakdown.get(code))
        if value is not None:
            parts.append(BankRatePart(code=code, title=title, percent=value))
    raw_rate = _percent(breakdown.get("raw_rate"))
    if raw_rate is not None and row["rate_percent"] is not None:
        adjustment = row["rate_percent"] - raw_rate
        if adjustment:
            parts.append(
                BankRatePart(
                    code="rounding_corridor",
                    title="Округление и коридор продукта",
                    percent=adjustment,
                )
            )
    recommendation = explain.get("recommendation")
    return BankDecision(
        **summary(row).model_dump(),
        inputs_hash=row["inputs_hash"],
        snapshot_ids=row["snapshot_ids"],
        recommendation=BankRecommendation.model_validate(recommendation)
        if recommendation
        else None,
        reasons=reasons,
        manual_reasons=manual_reasons(explain),
        score=row["score"],
        grade=row["grade"],
        pd_percent=_percent(row["pd"]),
        factors=factors,
        revenue_monthly_rub=row["revenue_monthly_rub"],
        free_cash_flow_rub=row["free_cash_flow_rub"],
        existing_payments_rub=numbers.get("existing_payments_rub"),
        payment_rub=row["payment_rub"],
        last_payment_rub=numbers.get("last_payment_rub"),
        overpayment_rub=numbers.get("overpayment_rub"),
        stress_shock_percent=_percent(numbers.get("stress_shock")),
        max_amount_rub=row["max_amount_rub"],
        checks=checks,
        rate=BankRate(
            rate_percent=row["rate_percent"],
            raw_rate_percent=_percent(breakdown.get("raw_rate")),
            corridor_min_percent=_percent(breakdown.get("corridor_min")),
            corridor_max_percent=_percent(breakdown.get("corridor_max")),
            rate_with_collateral_percent=_percent(breakdown.get("rate_with_collateral")),
            parts=parts,
        ),
        flags=[r.code for r in reasons if r.kind == "FLAG"],
        features=row["features"],
        variants=[
            BankVariant(
                kind=v["kind"],
                product_code=v["product"],
                amount_rub=v["amount_rub"],
                term_months=v["term_months"],
                rate_percent=Decimal(str(v["rate"])) * 100,
                payment_rub=v["payment_rub"],
                dscr=v.get("dscr"),
                stress_dscr=v.get("stress_dscr"),
                security_required=v.get("security_required", False),
                recommended=v.get("recommended", False),
                note=v.get("note", ""),
                requirements=v.get("requirements") or [],
            )
            for v in explain.get("variants") or []
        ],
        trace=explain.get("trace") or [],
        assessed_input=row["inputs"],
    )


def card(
    principal: auth.Principal, application_id: UUID, expected_version: int | None
) -> BankApplicationCard:
    require_bank(principal)
    with db.transaction() as session:
        data = queries.card_rows(session, application_id)
        if data is None:
            raise not_found("Заявка")
        app, decisions = data["application"], data["decisions"]
        current = decisions[0] if decisions else None
        engine = next((r for r in decisions if r["source"] == "ENGINE"), None)
        recommendation = (engine["explain"] or {}).get("recommendation") if engine else None
        used_ids = set(current["snapshot_ids"]) if current else set()
        return BankApplicationCard(
            id=app["id"],
            number=app["number"],
            status=app["status"],
            version=app["version"],
            stale=expected_version is not None and expected_version != app["version"],
            current_version_id=app["current_version_id"],
            product_code=app["product_code"],
            amount_rub=app["amount_rub"],
            term_months=app["term_months"],
            purpose_code=app["purpose_code"],
            draft=app["draft"],
            company=BankApplicant(
                id=app["company_id"],
                name=app["company_name"],
                inn=app["inn"],
                is_bank_customer=app["is_bank_customer"]
                if app["is_bank_customer"] is not None
                else ((engine or {}).get("features") or {}).get("is_bank_customer"),
                registered_on=app["registered_on"],
                status=app["company_status"],
                okved=app["okved"],
            ),
            submitted_by=BankSubmittedBy(
                id=app["created_by"], name=app["submitted_name"], company_role=app["submitted_role"]
            ),
            submitted_at=app["submitted_at"],
            decision=decision_view(current) if current else None,
            engine_decision_id=engine["id"] if engine else None,
            engine_recommendation=BankRecommendation.model_validate(recommendation)
            if recommendation
            else None,
            decisions=[summary(r) for r in decisions],
            source_snapshots=[
                BankSourceSnapshot.model_validate(
                    {**r, "used_by_current_decision": r["id"] in used_ids}
                )
                for r in data["snapshots"]
            ],
            history=[BankHistoryEvent.model_validate(r) for r in data["history"]],
            documents=None,
        )
