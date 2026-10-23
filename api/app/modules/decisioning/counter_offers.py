"""Встречные предложения (T-297, шаг 12, 30-10, вариант Г): оптимизатор и до трёх карточек.

Если запрос не проходит, а клиент хороший, ядро перебирает условия и показывает до трёх разных
компромиссов. Каждый обязан пройти те же проверки, что и обычный запрос, но строже: DSCR ≥ 1,30,
стресс-DSCR ≥ 1,05, долг к выручке < 0,95 (запас над серыми зонами 30-11, иначе встречное само
ушло бы человеку). Дополнительно: правила продукта, допустимый грейд, предел продукта, авто-лимит.

Перебор: продукты × сроки × «залог был / добавлен» × суммы с шагом из политики. Условие прохождения
монотонно по сумме (платёж, долг, предел продукта, залоговый порог растут вместе с ней), поэтому
для каждой связки «продукт, срок, залог» наибольшая проходящая сумма находится делением пополам, а
не перебором всех сумм: так счёт укладывается в миллисекунды. Расстояние до запроса не растёт с
ростом суммы при весах политики (вес суммы больше половины веса переплаты на любой рост), поэтому
лучшая сумма связки — наибольшая проходящая (проверено сверкой с полным перебором в тестах).

Три карточки (30-10):
  * `LONGER_TERM` — запрошенная сумма, наименьший срок сетки, на котором она проходит
    (`OTHER_TERM`, если он короче запрошенного: запрошенный срок вне рамок продукта);
  * `LESS_AMOUNT` — запрошенный срок, наибольшая проходящая сумма;
  * `OTHER_PRODUCT` / `WITH_SECURITY` — лучшая по расстоянию среди связок с другим продуктом
    или с залогом, которого клиент не предлагал.
«Рекомендуем» — карточка с наименьшим расстоянием; при равенстве — по порядку карточек.
Все тексты — данные в `texts_ru`, веса и сетка сроков — в `policy.counter_offers`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from app.modules.decisioning import loan_math as lm
from app.modules.decisioning import pricing
from app.modules.decisioning.affordability import (
    Affordability,
    meets_counter_thresholds,
    product_cap,
    schedule_numbers,
)
from app.modules.decisioning.dates import ceil_months_between
from app.modules.decisioning.policy import Policy
from app.modules.decisioning.products import ProductContext, auto_limit, check_product
from app.modules.decisioning.texts_ru import (
    format_money,
    variant_requirements,
    variant_why,
)
from app.modules.decisioning.types import (
    Application,
    ContractInfo,
    Features,
    Grade,
    ParamValue,
    Product,
    Variant,
)

STATUS_READY = "READY"
STATUS_NONE = "NOT_APPLICABLE"
_Q6 = Decimal("0.000001")
# Продукты, которые можно предложить вместо запрошенного: инвестиционный нужен под конкретную
# покупку и всегда идёт человеку, овердрафт не имеет графика платежей для DSCR
_ALTERNATIVES = (
    Product.EXPRESS,
    Product.WORKING_CAPITAL,
    Product.CONTRACT,
    Product.CREDIT_LINE,
)


@dataclass(frozen=True, slots=True)
class CounterOfferSearch:
    """Итог поиска. `variants` — карточки в пределах авто-лимита; `feasible` — есть хоть один
    проходящий вариант (в том числе выше полномочий, C-04: тогда решает человек)."""

    status: str
    variants: tuple[Variant, ...]
    feasible: bool
    probe: dict[str, ParamValue]
    above_authority: bool = False
    # Для причины AMOUNT_ABOVE_AUTO_LIMIT, если автоматических карточек нет, а выше лимита есть
    authority: dict[str, ParamValue] = field(default_factory=dict)


NOT_SEARCHED = CounterOfferSearch(STATUS_NONE, (), False, {})


# ---------------------------------------------------------------- внутренние типы


@dataclass(frozen=True, slots=True)
class _Group:
    """Связка «продукт, срок, залог»: внутри неё проходящие суммы образуют отрезок снизу."""

    product: Product
    term: int
    added: bool  # залог добавлен сверх заявки (клиент его не предлагал)
    rate: Decimal
    repayment: str
    pctx: ProductContext


@dataclass(frozen=True, slots=True)
class _Candidate:
    group: _Group
    amount: int
    payment: int
    last_payment: int | None
    overpayment: int | None
    distance: Decimal

    @property
    def rank(self) -> tuple[Decimal, int, int, int, bool]:
        """Равные расстояния: меньший срок, затем большая сумма, затем порядок продуктов."""
        order = list(Product).index(self.group.product)
        return self.distance, self.group.term, -self.amount, order, self.group.added


class _Search:
    """Поиск по одной заявке. Объект живёт один вызов; кэши — только внутри него."""

    def __init__(  # noqa: PLR0913 — входы шагов 6–10 `decide`, других источников нет
        self,
        policy: Policy,
        app: Application,
        feats: Features,
        grade: Grade,
        pctx: ProductContext,
        contract: ContractInfo | None,
        inflow_average: int | None,
        request: Affordability,
        *,
        limit_on: bool,
    ) -> None:
        self.policy = policy
        self.app = app
        self.feats = feats
        self.grade = grade
        self.pctx = pctx
        self.contract = contract
        self.inflow = inflow_average
        self.request = request
        self.limit_on = limit_on
        co = policy.counter_offers
        self.co = co
        self.step = co.amount_step_rub.value
        self.weights = co.weights
        self.term_scale = Decimal(max(co.term_grid_months.value))
        self.flow = feats.flow_model_rub or 0
        self.existing = feats.existing_payments_rub
        self.shock = feats.stress_shock
        self.limits: dict[Product, int | None] = {}
        self.caps: dict[Product, int | None] = {}
        self.rates: dict[tuple[Product, bool], Decimal] = {}
        young_limit = policy.restrictions.business_too_young.value
        age = feats.business_age_months
        # Молодой бизнес без обеспечения: любой вариант без него снова стал бы условным встречным
        self.needs_security = age is not None and age < young_limit and not feats.security_confirmed
        self.can_add_collateral = not feats.collateral_provided

    # ------------------------------------------------------------ связки и проверки

    def terms(self, product: Product) -> list[int]:
        cfg = self.policy.product_config(product.value)
        if cfg.requires_contract:
            if self.contract is None:
                return []
            return [ceil_months_between(self.pctx.app_today, self.contract.payment_deadline) + 1]
        if cfg.repayment.value == "OVERDRAFT":
            return [cfg.term_min_months]
        grid = {
            t
            for t in (*self.co.term_grid_months.value, self.app.term_months)
            if cfg.term_min_months <= t <= cfg.term_max_months
        }
        return sorted(grid)

    def group(self, product: Product, term: int, *, added: bool) -> _Group:
        collateral = self.feats.collateral_provided or added
        pctx = replace(
            self.pctx,
            collateral_provided=collateral,
            security_confirmed=self.feats.security_confirmed or added,
        )
        cfg = self.policy.product_config(product.value)
        key = (product, collateral)
        if key not in self.rates:
            self.rates[key] = pricing.rate_for(self.policy, product, self.grade, collateral).rate
        return _Group(product, term, added, self.rates[key], cfg.repayment.value, pctx)

    def _limit(self, product: Product) -> int | None:
        if product not in self.limits:
            self.limits[product] = auto_limit(self.policy, product, self.grade)
        return self.limits[product]

    def _cap(self, product: Product) -> int | None:
        if product not in self.caps:
            cap = product_cap(
                self.policy, product, self.feats, self.app, self.contract, self.inflow
            )
            self.caps[product] = None if cap is None else cap[1]
        return self.caps[product]

    def passes(self, g: _Group, amount: int) -> bool:
        """Все проверки встречного для одной суммы (то же, что `decide` для обычного запроса)."""
        if self.limit_on:
            limit = self._limit(g.product)
            if limit is not None and amount > limit:
                return False
        if check_product(self.policy, g.product, amount, g.term, g.pctx):
            return False
        cap = self._cap(g.product)
        if cap is not None and amount > cap:
            return False
        annual = self.feats.revenue_annual_rub
        debt_ratio = (
            Decimal(self.feats.total_debt_rub + amount) / Decimal(annual) if annual else None
        )
        if g.repayment == "OVERDRAFT":  # платежа по графику нет: DSCR не считается
            below = self.co.debt_to_revenue_below.value
            return debt_ratio is None or debt_ratio < below
        payment = lm.payment_for(g.repayment, amount, g.rate, g.term)
        return meets_counter_thresholds(
            self.policy, self.flow, self.existing, payment, self.shock, debt_ratio
        )

    def best_amount(self, g: _Group, top: int) -> int | None:
        """Наибольшая проходящая сумма ≤ `top`: сама `top`, иначе кратная шагу, иначе `None`."""
        step = self.step
        floor = -(-max(self.policy.product_config(g.product.value).amount_min_rub, 1) // step)
        lowest = floor * step
        if top < lowest or not self.passes(g, lowest):
            return (
                None  # снизу проходящий отрезок начинается с минимума: не проходит он — нет связки
            )
        if self.passes(g, top):
            return top
        lo, hi = floor, (top - 1) // step  # lo проходит, top — нет
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.passes(g, mid * step):
                lo = mid
            else:
                hi = mid - 1
        return lo * step

    # ------------------------------------------------------------ кандидат и расстояние

    def distance(self, g: _Group, amount: int, overpayment: int | None) -> Decimal:
        w = self.weights
        asked = Decimal(self.app.amount_rub)
        loss = Decimal(max(self.app.amount_rub - amount, 0)) / asked
        growth = Decimal(max(g.term - self.app.term_months, 0)) / self.term_scale
        extra = Decimal(max((overpayment or 0) - (self.request.overpayment_rub or 0), 0)) / asked
        total = w.amount * loss + w.term * growth + w.overpayment * extra
        if g.product != self.app.product:
            total += w.product_change
        if g.added:
            total += w.security
        return total.quantize(_Q6)

    def candidate(self, g: _Group, amount: int) -> _Candidate:
        payment, last, over = schedule_numbers(g.repayment, amount, g.rate, g.term)
        return _Candidate(g, amount, payment, last, over, self.distance(g, amount, over))

    def lower_bound(self, g: _Group, amount: int) -> Decimal:
        """Расстояние без переплаты (она не отрицательна): отсекает заведомо худшие связки."""
        return self.distance(g, amount, self.request.overpayment_rub or 0)

    # ------------------------------------------------------------ три карточки

    def same_group(self, term: int) -> _Group:
        return self.group(self.app.product, term, added=False)

    def longer_term(self) -> _Candidate | None:
        """Запрошенная сумма и наименьший срок сетки, на котором она проходит."""
        if self.needs_security:
            return None
        for term in self.terms(self.app.product):
            if term == self.app.term_months:
                continue
            g = self.same_group(term)
            if self.passes(g, self.app.amount_rub):
                return self.candidate(g, self.app.amount_rub)
        return None

    def less_amount(self) -> _Candidate | None:
        """Запрошенный срок и наибольшая проходящая сумма меньше запрошенной."""
        if self.needs_security:
            return None
        g = self.same_group(self.app.term_months)
        top = (self.app.amount_rub - 1) // self.step * self.step
        amount = self.best_amount(g, top)
        return None if amount is None else self.candidate(g, amount)

    def other(self) -> _Candidate | None:
        """Лучший по расстоянию среди связок с другим продуктом или добавленным залогом."""
        products = [self.app.product, *(p for p in _ALTERNATIVES if p != self.app.product)]
        best: _Candidate | None = None
        for product in products:
            for added in (False, True):
                if added and not self.can_add_collateral:
                    continue
                if not added and (product == self.app.product or self.needs_security):
                    continue  # это не «другое»: запрошенный продукт без нового обеспечения
                for term in self.terms(product):
                    g = self.group(product, term, added=added)
                    amount = self.best_amount(g, self.app.amount_rub)
                    if amount is None:
                        continue
                    if best is not None and self.lower_bound(g, amount) > best.distance:
                        continue
                    cand = self.candidate(g, amount)
                    if best is None or cand.rank < best.rank:
                        best = cand
        return best

    def cards(self) -> list[tuple[str, _Candidate]]:
        found: list[tuple[str, _Candidate]] = []
        if (a := self.longer_term()) is not None:
            # Срок короче запрошенного бывает, когда запрошенный вне рамок продукта (например, 48 мес.)
            found.append(
                ("LONGER_TERM" if a.group.term > self.app.term_months else "OTHER_TERM", a)
            )
        if (b := self.less_amount()) is not None:
            found.append(("LESS_AMOUNT", b))
        if (c := self.other()) is not None:
            kind = "OTHER_PRODUCT" if c.group.product != self.app.product else "WITH_SECURITY"
            found.append((kind, c))
        return found

    # ------------------------------------------------------------ сборка карточки

    def variant(self, kind: str, cand: _Candidate, *, recommended: bool) -> Variant:
        g = cand.group
        cfg = self.policy.product_config(g.product.value)
        if g.repayment == "OVERDRAFT":
            dscr = stress = None
        else:
            dscr = lm.dscr(self.flow, self.existing, cand.payment).quantize(_Q6)
            stress = lm.stress_dscr(self.flow, self.existing, cand.payment, self.shock).quantize(
                _Q6
            )
        payment = format_money(cand.payment)
        note = variant_why(
            kind,
            bullet=g.repayment == "BULLET",
            term=str(g.term),
            payment=payment,
            title=cfg.title,
        )
        contract_number = (
            self.contract.registry_number if g.repayment == "BULLET" and self.contract else None
        )
        return Variant(
            kind=kind,
            product=g.product,
            amount_rub=cand.amount,
            term_months=g.term,
            rate=g.rate,
            payment_rub=cand.payment,
            dscr=dscr,
            stress_dscr=stress,
            security_required=g.added,
            recommended=recommended,
            note=note,
            requirements=variant_requirements(
                contract_number=contract_number, security_added=g.added
            ),
            last_payment_rub=cand.last_payment,
            overpayment_rub=cand.overpayment,
            distance=cand.distance,
        )


def _probe(
    policy: Policy, app: Application, rate: Decimal, feats: Features
) -> dict[str, ParamValue]:
    """Минимальная сумма на максимальный срок запрошенного продукта: для текста `NO_OFFER_FOUND`."""
    cfg = policy.product_config(app.product.value)
    step = policy.counter_offers.amount_step_rub.value
    amount = ((max(step, cfg.amount_min_rub) + step - 1) // step) * step
    grid = [
        t
        for t in policy.counter_offers.term_grid_months.value
        if cfg.term_min_months <= t <= cfg.term_max_months
    ]
    term = max(grid) if grid else cfg.term_max_months
    payment = lm.payment_for(cfg.repayment.value, amount, rate, term)
    return {"amount_rub": amount, "term_months": term, "payment_rub": payment}


def search_counter_offers(  # noqa: PLR0913 — входы шагов 6–10 `decide`, других источников нет
    policy: Policy,
    app: Application,
    rate: Decimal,
    feats: Features,
    *,
    grade: Grade,
    product_ctx: ProductContext,
    contract: ContractInfo | None,
    inflow_average: int | None,
    request: Affordability,
) -> CounterOfferSearch:
    """Оптимизатор встречных: до трёх карточек в пределах авто-лимита.

    Если автоматических карточек нет, повторяет поиск без авто-лимита: проходящие варианты выше
    полномочий дают `above_authority` (решает человек, C-04). Нет и таких — `feasible = False`.
    """
    probe = _probe(policy, app, rate, feats)
    auto = _Search(
        policy, app, feats, grade, product_ctx, contract, inflow_average, request, limit_on=True
    )
    found = auto.cards()
    if found:
        return _ready(auto, found, probe)
    manual = _Search(
        policy, app, feats, grade, product_ctx, contract, inflow_average, request, limit_on=False
    )
    beyond = manual.cards()
    if not beyond:
        return CounterOfferSearch(STATUS_NONE, (), False, probe)
    best = min((cand for _, cand in beyond), key=lambda c: c.rank)
    limit = auto_limit(policy, best.group.product, grade)
    return CounterOfferSearch(
        STATUS_NONE,
        (),
        True,
        probe,
        above_authority=True,
        authority={"amount_rub": best.amount, "limit_rub": limit or 0, "grade": grade.value},
    )


def _ready(
    search: _Search, found: list[tuple[str, _Candidate]], probe: dict[str, ParamValue]
) -> CounterOfferSearch:
    limit = search.co.max_cards.value
    if len(found) > limit:  # в карточки попадают самые близкие к запросу, порядок карточек прежний
        keep = sorted(found, key=lambda item: item[1].rank)[:limit]
        found = [item for item in found if item in keep]
    nearest = min(found, key=lambda item: item[1].rank)
    variants = tuple(
        search.variant(kind, cand, recommended=(kind, cand) == nearest) for kind, cand in found
    )
    return CounterOfferSearch(STATUS_READY, variants, True, probe)


def conditional_security_variant(app: Application, rate: Decimal, afford: Affordability) -> Variant:
    """«Тот же запрос с поручительством владельца или залогом» (молодой бизнес без обеспечения)."""
    return Variant(
        kind="CONDITIONAL_SECURITY",
        product=app.product,
        amount_rub=app.amount_rub,
        term_months=app.term_months,
        rate=rate,
        payment_rub=afford.payment_rub,
        dscr=afford.dscr if afford.dscr is not None else Decimal(0),
        stress_dscr=afford.stress_dscr if afford.stress_dscr is not None else Decimal(0),
        security_required=True,
        recommended=True,
        note="тот же запрос с поручительством владельца или залогом",
    )
