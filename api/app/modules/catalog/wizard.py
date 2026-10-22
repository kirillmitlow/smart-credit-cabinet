"""Мастер подбора (T-242, 10-07, D-011, D-017): ответы → продукт по таблице правил из конфига.

Продукт выбирает таблица `wizard.rules`, не модель (D-060): один и тот же набор ответов даёт один
и тот же результат, пришёл он кнопками или текстом. Каждый кандидат проходит те же требования
продукта, что и в ядре (`service.evaluate` → `decisioning.check_product`); тот, кто не прошёл, не
показывается основным, а его причина лежит в `rejected`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.decisioning import Policy, max_payment
from app.modules.decisioning.policy import WizardRule, WizardWhen

from .calculator import calculate
from .facts import CompanyFacts, product_context
from .schemas import (
    AutoDecisionMode,
    ComfortableOption,
    DecisionTime,
    PaymentKind,
    Recommended,
    RejectedCandidate,
    WizardAnswers,
    WizardOutcome,
    WizardResult,
)
from .service import (
    Evaluation,
    auto_decision,
    clamp,
    evaluate,
    hint_for,
    is_young,
    reason_out,
)

NO_PURPOSE_HINT = "Расскажите, на что нужны деньги, или выберите продукт в каталоге"
NOTHING_FITS_HINT = (
    "По этим условиям подходящих продуктов нет: загляните в каталог, "
    "там видно, что и когда станет доступно"
)


@dataclass(frozen=True, slots=True)
class Normalized:
    """Ответы, где «не знаю» (`UNKNOWN`, `null`) стало `None`."""

    purpose: str | None
    amount_rub: int | None
    frequency: str | None
    payback_horizon: str | None
    gov_contract: bool | None
    term_months: int | None
    collateral: str | None


def _known(value: str | None) -> str | None:
    return None if value in (None, "UNKNOWN") else value


def normalize(answers: WizardAnswers) -> Normalized:
    gov = _known(answers.gov_contract)
    return Normalized(
        purpose=_known(answers.purpose),
        amount_rub=answers.amount_rub,
        frequency=_known(answers.frequency),
        payback_horizon=_known(answers.payback_horizon),
        gov_contract=None if gov is None else gov == "YES",
        term_months=answers.term_months,
        collateral=_known(answers.collateral),
    )


def matches(when: WizardWhen, a: Normalized, *, client: bool, young: bool) -> bool:
    """Строка подходит, если выполнены все её условия; «не знаю» не подходит заданному условию."""
    if when.young_business is not None and when.young_business != young:
        return False
    if when.client is not None and when.client != client:
        return False
    for allowed, value in (
        (when.purpose, a.purpose),
        (when.frequency, a.frequency),
        (when.payback_horizon, a.payback_horizon),
    ):
        if allowed is not None and (value is None or value not in allowed):
            return False
    if when.gov_contract is not None and a.gov_contract != when.gov_contract:
        return False
    if when.amount_max_rub is not None and (
        a.amount_rub is None or a.amount_rub > when.amount_max_rub
    ):
        return False
    return not (
        when.amount_above_rub is not None
        and (a.amount_rub is None or a.amount_rub <= when.amount_above_rub)
    )


def find_rule(policy: Policy, a: Normalized, *, client: bool, young: bool) -> WizardRule | None:
    return next(
        (r for r in policy.wizard.rules if matches(r.when, a, client=client, young=young)), None
    )


def _decision_time(
    policy: Policy, code: str, amount_rub: int | None, *, manual_path: bool
) -> DecisionTime:
    if manual_path:
        return DecisionTime.MANUAL
    mode, up_to = auto_decision(policy, code)
    if mode is AutoDecisionMode.NEVER:
        return DecisionTime.MANUAL
    if mode is AutoDecisionMode.UP_TO and amount_rub is not None and up_to is not None:
        return DecisionTime.AUTO if amount_rub <= up_to else DecisionTime.MANUAL
    return DecisionTime.AUTO


def comfortable_options(
    policy: Policy, code: str, amount_rub: int, facts: CompanyFacts
) -> list[ComfortableOption]:
    """2–3 пары «срок → платёж → переплата»; по силам при известном потоке — помечен (10-07)."""
    cfg = policy.product_config(code)
    if cfg.repayment.value != "ANNUITY":
        return []
    terms = sorted(
        {
            t
            for t in policy.wizard.comfortable_terms_months
            if cfg.term_min_months <= t <= cfg.term_max_months
        }
    )
    if len(terms) < 2:
        terms = sorted({cfg.term_min_months, cfg.term_max_months})
    terms = terms[:3]
    p_max = (
        max_payment(facts.monthly_cash_flow_rub, 0, policy.affordability.dscr_min.value)
        if facts.monthly_cash_flow_rub is not None
        else None
    )
    options: list[ComfortableOption] = []
    marked = False
    for term in terms:
        calc = calculate(policy, code, amount_rub, term, None)
        fits = p_max is not None and calc.payment_rub <= p_max
        recommended = fits and not marked  # самый короткий из посильных
        marked = marked or fits
        options.append(
            ComfortableOption(
                term_months=term,
                payment_rub=calc.payment_rub,
                overpayment_rub=calc.overpayment_rub,
                recommended=recommended,
            )
        )
    return options


def _recommended(
    policy: Policy,
    code: str,
    why: str,
    ev: Evaluation,
    a: Normalized,
    facts: CompanyFacts,
    *,
    manual_path: bool,
    young: bool,
) -> Recommended:
    cfg = policy.product_config(code)
    payment: int | None = None
    kind: PaymentKind | None = None
    options: list[ComfortableOption] = []
    if a.amount_rub is not None:
        term = a.term_months or clamp(
            policy.wizard.default_term_months.value, cfg.term_min_months, cfg.term_max_months
        )
        calc = calculate(policy, code, a.amount_rub, term, None)
        payment, kind = calc.payment_rub, calc.payment_kind
        options = comfortable_options(policy, code, a.amount_rub, facts)
    return Recommended(
        product_code=code,
        title=cfg.title,
        why=why,
        payment_rub=payment,
        payment_kind=kind,
        rate_percent_from=cfg.base_rate * 100,
        decision_time=_decision_time(policy, code, a.amount_rub, manual_path=manual_path or young),
        documents=list(cfg.documents),
        needs_collateral=ev.needs_collateral,
        needs_contract=ev.needs_contract,
        requires_security=manual_path or young,
        comfortable_options=options,
    )


def recommend(
    policy: Policy, answers: WizardAnswers, facts: CompanyFacts, today: date
) -> WizardResult:
    """Основной продукт и одна альтернатива, либо «каталог с подсказкой»."""
    a = normalize(answers)
    ctx = product_context(facts, today)
    young = is_young(policy, facts, today)
    rule = find_rule(policy, a, client=facts.is_bank_customer, young=young)
    ask_collateral = (
        a.amount_rub is not None
        and a.amount_rub > policy.wizard.collateral_question_above_rub.value
        and a.collateral is None
    )
    if rule is None:
        return WizardResult(
            outcome=WizardOutcome.CATALOG_HINT,
            rule_id=None,
            start_path=False,
            primary=None,
            alternative=None,
            rejected=[],
            hint=NO_PURPOSE_HINT,
            ask_collateral=False,
        )

    valid: list[tuple[str, Evaluation]] = []
    rejected: list[RejectedCandidate] = []
    first_hint: str | None = None
    for code in (rule.primary, *rule.alternatives):
        ev = evaluate(policy, code, ctx, a.amount_rub, a.term_months)
        if ev.ok:
            valid.append((code, ev))
            continue
        cfg = policy.product_config(code)
        rejected.append(
            RejectedCandidate(
                product_code=code,
                title=cfg.title,
                reasons=[reason_out(r, facts) for r in ev.blocking],
            )
        )
        first_hint = first_hint or hint_for(ev.blocking, cfg)

    hint: str | None = None
    if rule.future_hint is not None:
        future = evaluate(policy, rule.future_hint, ctx)
        if not future.ok:
            hint = hint_for(future.blocking, policy.product_config(rule.future_hint))
    if not valid:
        return WizardResult(
            outcome=WizardOutcome.CATALOG_HINT,
            rule_id=rule.id,
            start_path=rule.start_path,
            primary=None,
            alternative=None,
            rejected=rejected,
            hint=first_hint or hint or NOTHING_FITS_HINT,
            ask_collateral=False,
        )

    def build(index: int, why: str) -> Recommended:
        code, ev = valid[index]
        return _recommended(
            policy, code, why, ev, a, facts, manual_path=rule.start_path, young=young
        )

    primary_code = valid[0][0]
    primary = build(
        0, rule.why if primary_code == rule.primary else policy.product_config(primary_code).purpose
    )
    alternative = None
    if len(valid) > 1:
        alt_code = valid[1][0]
        alternative = build(1, policy.product_config(alt_code).purpose)
    return WizardResult(
        outcome=WizardOutcome.RECOMMENDED,
        rule_id=rule.id,
        start_path=rule.start_path,
        primary=primary,
        alternative=alternative,
        rejected=rejected,
        hint=hint,
        ask_collateral=ask_collateral,
    )
