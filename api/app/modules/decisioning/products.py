"""Правила продукта одной функцией для мастера, каталога и ядра (T-294, D-018, 10-06).

Иначе клиент увидел бы «подходит», а получил отказ. Новый продукт — запись в политике, не код.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.modules.decisioning.dates import add_months, ceil_months_between
from app.modules.decisioning.loan_math import floor_rub
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.reasons import make
from app.modules.decisioning.types import ContractInfo, Grade, Level, Product, ReasonCode


@dataclass(frozen=True, slots=True)
class ProductContext:
    """Всё, что нужно правилам продукта, кроме суммы и срока."""

    app_today: date
    business_age_months: int | None
    registration_date: date | None
    is_bank_customer: bool
    customer_turnover_months: int
    collateral_provided: bool
    security_confirmed: bool
    grade: Grade | None = None
    contract: ContractInfo | None = None


def auto_limit(policy: Policy, product: Product, grade: Grade) -> int | None:
    """Авто-лимит суммы: B — колонка каталога, A — вдвое выше, не выше максимума продукта.

    `None` — без предела (овердрафт ограничен долей поступлений). Для C и D автомата нет:
    маршрут решает `GRADE_NEEDS_REVIEW`, а не лимит суммы.
    """
    cfg = policy.product_config(product.value)
    if cfg.grade_access[grade.value].value != "AUTO":
        return 0
    if cfg.auto_limit_b_rub is None:
        return None
    if grade == Grade.A:
        multiplier = policy.routing.grade_a_auto_multiplier.value
        return min(cfg.auto_limit_b_rub * multiplier, cfg.amount_max_rub)
    return cfg.auto_limit_b_rub


def check_product(
    policy: Policy, product: Product, amount_rub: int, term_months: int, ctx: ProductContext
) -> tuple[ReasonCode, ...]:
    """Нарушения требований продукта; пустой кортеж — подходит. Собираются все, не первое."""
    cfg = policy.product_config(product.value)
    out: list[ReasonCode] = []

    if (
        not cfg.amount_min_rub <= amount_rub <= cfg.amount_max_rub
        or not cfg.term_min_months <= term_months <= cfg.term_max_months
    ):
        out.append(
            make(
                "AMOUNT_OUT_OF_RANGE",
                product=product.value,
                amount_rub=amount_rub,
                term_months=term_months,
                amount_min_rub=cfg.amount_min_rub,
                amount_max_rub=cfg.amount_max_rub,
                term_min_months=cfg.term_min_months,
                term_max_months=cfg.term_max_months,
            )
        )

    if (
        ctx.business_age_months is not None
        and ctx.business_age_months < cfg.min_business_age_months
    ):
        available = (
            add_months(ctx.registration_date, cfg.min_business_age_months).isoformat()
            if ctx.registration_date
            else None
        )
        out.append(
            make(
                "PRODUCT_AGE_MIN",
                product=product.value,
                required_months=cfg.min_business_age_months,
                age_months=ctx.business_age_months,
                available_from=available,
            )
        )

    if cfg.requires_bank_customer and (
        not ctx.is_bank_customer or ctx.customer_turnover_months < cfg.min_customer_turnover_months
    ):
        out.append(
            make(
                "NOT_BANK_CLIENT",
                is_client=ctx.is_bank_customer,
                turnover_months=ctx.customer_turnover_months,
                required_months=cfg.min_customer_turnover_months,
            )
        )

    threshold = cfg.collateral_required_above_rub
    if threshold is not None and amount_rub > threshold and not ctx.collateral_provided:
        out.append(
            make(
                "COLLATERAL_REQUIRED",
                product=product.value,
                amount_rub=amount_rub,
                threshold_rub=threshold,
            )
        )

    if ctx.grade is not None:
        out.extend(_grade_violations(policy, product, amount_rub, ctx, ctx.grade))

    if cfg.requires_contract:
        out.extend(_contract_violations(amount_rub, term_months, ctx))
    return tuple(out)


def _grade_violations(
    policy: Policy, product: Product, amount_rub: int, ctx: ProductContext, grade: Grade
) -> list[ReasonCode]:
    cfg = policy.product_config(product.value)
    if cfg.grade_access[grade.value].value == "NO":
        return [
            make("GRADE_NOT_ALLOWED", grade=grade.value, product=product.value, why="NOT_OFFERED")
        ]
    if grade == Grade.D:
        if cfg.grade_d_requires == "COLLATERAL" and not ctx.collateral_provided:
            return [
                make("GRADE_NOT_ALLOWED", grade="D", product=product.value, why="NEEDS_COLLATERAL")
            ]
        if cfg.grade_d_requires == "SECURITY" and not ctx.security_confirmed:
            return [
                make("GRADE_NOT_ALLOWED", grade="D", product=product.value, why="NEEDS_SECURITY")
            ]
        share = cfg.grade_d_max_share_of_max
        if share is not None and Decimal(amount_rub) > Decimal(cfg.amount_max_rub) * share:
            return [
                make(
                    "GRADE_NOT_ALLOWED",
                    grade="D",
                    product=product.value,
                    why="AMOUNT_ABOVE_HALF_OF_MAX",
                    max_rub=floor_rub(Decimal(cfg.amount_max_rub) * share),
                )
            ]
    return []


def _contract_violations(
    amount_rub: int, term_months: int, ctx: ProductContext
) -> list[ReasonCode]:
    contract = ctx.contract
    if contract is None:
        return [
            make(
                "CONTRACT_INVALID",
                reason="NOT_FOUND",
                reason_text=_CONTRACT_TEXT["NOT_FOUND"],
                registry_number=None,
                status=None,
                payment_deadline=None,
                paid_rub=None,
            )
        ]
    reason = _contract_problem(contract, term_months, ctx.app_today)
    if reason is None:
        return []
    return [
        make(
            "CONTRACT_INVALID",
            reason=reason,
            reason_text=_CONTRACT_TEXT[reason],
            registry_number=contract.registry_number,
            status=contract.status,
            payment_deadline=contract.payment_deadline.isoformat(),
            paid_rub=contract.paid_rub,
        )
    ]


_CONTRACT_TEXT = {
    "NOT_FOUND": "контракт не найден в реестре закупок",
    "STATUS": "он уже исполнен или расторгнут",
    "PAYMENT_DEADLINE_PASSED": "срок оплаты уже прошёл",
    "ALREADY_PAID": "он уже полностью оплачен",
    "TERM_AFTER_PAYMENT": "срок кредита больше срока оплаты контракта плюс месяц",
}


def _contract_problem(contract: ContractInfo, term_months: int, today: date) -> str | None:
    if contract.status != "IN_PROGRESS":
        return "STATUS"
    if contract.payment_deadline < today:
        return "PAYMENT_DEADLINE_PASSED"
    if contract.paid_rub >= contract.price_rub:
        return "ALREADY_PAID"
    if term_months > ceil_months_between(today, contract.payment_deadline) + 1:
        return "TERM_AFTER_PAYMENT"
    return None


def authority_level(policy: Policy, amount_rub: int, grade: Grade | None) -> Level:
    """Матрица полномочий (30-11): сумма × грейд → L1/L2. Без грейда или E — осторожно L2."""
    for row in policy.routing.authority:
        if row.up_to_rub is None or amount_rub <= row.up_to_rub:
            if grade in (Grade.A, Grade.B):
                return Level(row.grade_ab)
            if grade == Grade.C:
                return Level(row.grade_c)
            return Level(row.grade_d)
    raise ValueError("матрица полномочий не покрывает сумму")
