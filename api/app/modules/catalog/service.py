"""Каталог продуктов и их доступность компании (T-240, 10-06).

Требования продукта проверяет `decisioning.check_product` — та же функция, что в ядре решения
(D-018): «показали, а потом отказали» невозможно. Здесь только оболочка: подставить границы,
разделить причины на «блокирует» и «потребуется позже» и по-человечески объяснить.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.decisioning import (
    Grade,
    Policy,
    Product,
    ProductContext,
    ReasonCode,
    add_months,
    auto_limit,
    check_product,
    render,
)
from app.modules.decisioning.policy import ProductConfig
from app.shared.errors import AppError

from .facts import CompanyFacts, business_age_months, product_context
from .schemas import AutoDecisionMode, ProductOut, ProductReasonOut

# Не блокируют показ: залог и контракт клиент добавит позже, это не «недоступно»
SOFT_CODES = frozenset({"COLLATERAL_REQUIRED", "CONTRACT_INVALID"})
PRODUCT_ORDER = ("EXPRESS", "WORKING_CAPITAL", "CONTRACT", "CREDIT_LINE", "OVERDRAFT", "INVESTMENT")


@dataclass(frozen=True, slots=True)
class Evaluation:
    blocking: tuple[ReasonCode, ...]
    needs_collateral: bool
    needs_contract: bool

    @property
    def ok(self) -> bool:
        return not self.blocking


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def evaluate(
    policy: Policy,
    code: str,
    ctx: ProductContext,
    amount_rub: int | None = None,
    term_months: int | None = None,
) -> Evaluation:
    """Подходит ли продукт компании. Сумма и срок не названы — проверяем границы продукта целиком."""
    cfg = policy.product_config(code)
    amount = amount_rub if amount_rub is not None else cfg.amount_min_rub
    term = (
        term_months
        if term_months is not None
        else clamp(
            policy.wizard.default_term_months.value, cfg.term_min_months, cfg.term_max_months
        )
    )
    reasons = check_product(policy, Product(code), amount, term, ctx)
    return Evaluation(
        blocking=tuple(r for r in reasons if r.code not in SOFT_CODES),
        needs_collateral=any(r.code == "COLLATERAL_REQUIRED" for r in reasons),
        needs_contract=cfg.requires_contract,
    )


def is_young(policy: Policy, facts: CompanyFacts, today: date) -> bool:
    """Бизнес моложе порога `BUSINESS_TOO_YOUNG` (D-035): кредит только с обеспечением (D-077)."""
    age = business_age_months(facts, today)
    return age is not None and age < policy.restrictions.business_too_young.value


def _available_from(reason: ReasonCode, facts: CompanyFacts) -> date | None:
    if reason.code == "PRODUCT_AGE_MIN":
        raw = reason.params.get("available_from")
        return date.fromisoformat(str(raw)) if raw else None
    if reason.code == "NOT_BANK_CLIENT" and facts.is_bank_customer and facts.customer_since:
        months = reason.params.get("required_months")
        return add_months(facts.customer_since, int(str(months))) if months is not None else None
    return None


def reason_out(reason: ReasonCode, facts: CompanyFacts) -> ProductReasonOut:
    explanation = render(reason)
    return ProductReasonOut(
        code=reason.code,
        text=explanation.client,
        action=explanation.action,
        available_from=_available_from(reason, facts),
    )


def hint_for(reasons: tuple[ReasonCode, ...], cfg: ProductConfig) -> str | None:
    """«Станет доступен…»: не тупик, а понятный путь (10-06, «Нет подходящего продукта»)."""
    for reason in reasons:
        if reason.code == "NOT_BANK_CLIENT":
            months = reason.params.get("required_months")
            return f"{cfg.title} станет доступен после {months} мес. обслуживания у нас"
        if reason.code == "PRODUCT_AGE_MIN":
            months = reason.params.get("required_months")
            return f"{cfg.title} станет доступен, когда бизнесу исполнится {months} мес."
    return None


def auto_decision(policy: Policy, code: str) -> tuple[AutoDecisionMode, int | None]:
    limit = auto_limit(policy, Product(code), Grade.B)
    if limit is None:
        return AutoDecisionMode.ALWAYS, None
    if limit == 0:
        return AutoDecisionMode.NEVER, None
    return AutoDecisionMode.UP_TO, limit


def product_view(
    policy: Policy, code: str, facts: CompanyFacts, today: date, ctx: ProductContext | None = None
) -> ProductOut:
    cfg = policy.product_config(code)
    ctx = ctx or product_context(facts, today)
    result = evaluate(policy, code, ctx)
    mode, up_to = auto_decision(policy, code)
    return ProductOut(
        code=code,
        title=cfg.title,
        purpose=cfg.purpose,
        repayment=cfg.repayment.value,
        amount_min_rub=cfg.amount_min_rub,
        amount_max_rub=cfg.amount_max_rub,
        term_min_months=cfg.term_min_months,
        term_max_months=cfg.term_max_months,
        collateral_required_above_rub=cfg.collateral_required_above_rub,
        rate_percent_from=cfg.base_rate * 100,
        auto_decision_mode=mode,
        auto_decision_up_to_rub=up_to,
        requires_bank_customer=cfg.requires_bank_customer,
        requires_contract=cfg.requires_contract,
        documents=list(cfg.documents),
        available=result.ok,
        unavailable_reasons=[reason_out(r, facts) for r in result.blocking],
        hint=hint_for(result.blocking, cfg),
        requires_security=is_young(policy, facts, today),
    )


def list_products(policy: Policy, facts: CompanyFacts, today: date) -> list[ProductOut]:
    ctx = product_context(facts, today)
    codes = [c for c in PRODUCT_ORDER if c in policy.catalog.products]
    codes += [
        c for c in policy.catalog.products if c not in codes
    ]  # новый продукт — запись в конфиге
    return [product_view(policy, c, facts, today, ctx) for c in codes]


def get_product(policy: Policy, code: str, facts: CompanyFacts, today: date) -> ProductOut:
    if code not in policy.catalog.products:
        raise AppError(404, "NOT_FOUND", "Продукт не найден")
    return product_view(policy, code, facts, today)
