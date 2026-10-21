"""Генераторы входов `decide()` для property-тестов (70-02, «Заметки для реализации»).

«Реалистичная компания»: возраст 0–20 лет, выручка от сотен тысяч до десятков миллионов,
0–3 обязательства, пропуски. Вход собирается из параметров `RequestParams`, чтобы тест мог
изменить один параметр и сравнить исходы (монотонность).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from hypothesis import strategies as st

from app.modules.decisioning import DecisionInput
from app.modules.decisioning.dates import add_months
from app.modules.decisioning.types import (
    BkiObligation,
    BkiReport,
    Collateral,
    CustomerData,
    FinancialsData,
    FinancialYear,
    Guarantor,
    Product,
    SubjectRole,
    TaxData,
    TurnoverData,
    TurnoverMonth,
)
from tests.fixtures import core_personas as cp

PRODUCTS = [Product.EXPRESS, Product.WORKING_CAPITAL, Product.CREDIT_LINE]


@dataclass(frozen=True)
class RequestParams:
    product: Product
    amount_rub: int
    term_months: int
    revenue_rub: int  # чистые поступления в месяц
    pct: tuple[int, ...]  # отклонение месяца от базы в процентах (длина = число месяцев)
    age_months: int
    tenure_months: int  # 0 — не клиент банка
    history_months: int
    closed_obligations: int
    monthly_payments_rub: int
    overdue_days: int
    inquiries: int
    rejected: int
    restructurings: int
    tax_debt_rub: int
    collateral_rub: int  # 0 — залога нет
    guarantor: bool
    with_financials: bool

    def to_input(self) -> DecisionInput:
        base = cp.t_base()
        today = cp.TODAY
        series = tuple(
            TurnoverMonth(
                m, self.revenue_rub * p // 100, self.revenue_rub * p // 100 * 85 // 100, 10
            )
            for m, p in zip(cp.month_starts(len(self.pct)), self.pct, strict=True)
        )
        overdue_rub = 100_000 if self.overdue_days else 0
        debt = self.monthly_payments_rub * 20
        company_report = BkiReport(
            has_history=self.history_months > 0,
            history_months=self.history_months,
            active_obligations=1,  # число обязательств не зависит от платежей («прочее равно»)
            closed_obligations=self.closed_obligations,
            total_debt_rub=debt,
            monthly_payments_rub=self.monthly_payments_rub,
            current_overdue_rub=overdue_rub,
            current_overdue_days=self.overdue_days,
            max_overdue_days_24m=self.overdue_days,
            restructurings_24m=self.restructurings,
            inquiries_30d_excl_own=self.inquiries,
            rejected_90d_excl_own=self.rejected,
            obligations=(
                BkiObligation(
                    "gen-active",
                    "LOAN",
                    monthly_payment_rub=self.monthly_payments_rub,
                    balance_rub=debt,
                ),
            ),
        )
        registry = replace(
            base.snapshot.registry, registration_date=add_months(today, -self.age_months)
        )
        customer = (
            CustomerData(cp.ok("abs"), True, add_months(today, -self.tenure_months))
            if self.tenure_months
            else CustomerData(cp.not_found("abs"), False)
        )
        financials = (
            FinancialsData(
                cp.ok("fin"),
                (
                    FinancialYear(2025, self.revenue_rub * 12, self.revenue_rub * 12 // 10, 0),
                    FinancialYear(2024, self.revenue_rub * 12, self.revenue_rub * 12 // 10, 0),
                ),
            )
            if self.with_financials
            else FinancialsData()
        )
        subjects = tuple(
            replace(s, report=company_report) if s.role == SubjectRole.COMPANY else s
            for s in base.snapshot.bki
        )
        snap = replace(
            base.snapshot,
            registry=registry,
            customer=customer,
            turnover=TurnoverData(cp.ok("abs"), series),
            financials=financials,
            tax=TaxData(cp.ok("tax"), regimes=("USN_INCOME",), tax_debt_rub=self.tax_debt_rub),
            bki=subjects,
        )
        app = replace(
            base.application,
            product=self.product,
            amount_rub=self.amount_rub,
            term_months=self.term_months,
            collateral=Collateral("залог", self.collateral_rub) if self.collateral_rub else None,
            guarantor=Guarantor("1", True) if self.guarantor else None,
        )
        return replace(base, application=app, snapshot=snap)


@st.composite
def request_params(draw: st.DrawFn) -> RequestParams:
    product = draw(st.sampled_from(PRODUCTS))
    lo, hi = {
        Product.EXPRESS: (100_000, 3_000_000),
        Product.WORKING_CAPITAL: (500_000, 30_000_000),
        Product.CREDIT_LINE: (1_000_000, 50_000_000),
    }[product]
    tlo, thi = {
        Product.EXPRESS: (6, 36),
        Product.WORKING_CAPITAL: (3, 36),
        Product.CREDIT_LINE: (12, 36),
    }[product]
    months = draw(st.integers(3, 24))
    return RequestParams(
        product=product,
        amount_rub=draw(st.integers(lo // 50_000, hi // 50_000)) * 50_000,
        term_months=draw(st.integers(tlo, thi)),
        # кратна 1000: ряд revenue·p/100 масштабируется точно, без «дрожания» округлений
        revenue_rub=draw(st.integers(300, 40_000)) * 1000,
        pct=tuple(draw(st.lists(st.integers(70, 130), min_size=months, max_size=months))),
        age_months=draw(st.integers(0, 240)),
        tenure_months=draw(st.sampled_from([0, 3, 12, 24, 48])),
        history_months=draw(st.sampled_from([0, 10, 30, 80])),
        closed_obligations=draw(st.integers(0, 3)),
        monthly_payments_rub=draw(st.sampled_from([0, 0, 20_000, 150_000, 600_000])),
        overdue_days=draw(st.sampled_from([0, 0, 0, 15, 45, 75, 95])),
        inquiries=draw(st.integers(0, 9)),
        rejected=draw(st.integers(0, 4)),
        restructurings=draw(st.sampled_from([0, 0, 0, 1])),
        tax_debt_rub=draw(st.sampled_from([0, 0, 0, 10_000, 200_000, 3_000_000])),
        collateral_rub=draw(st.sampled_from([0, 0, 2_000_000, 40_000_000])),
        guarantor=draw(st.booleans()),
        with_financials=draw(st.booleans()),
    )


def healthy(p: RequestParams) -> RequestParams:
    """Подправляет случайный запрос до «хорошего клиента»: автоодобрение возможно, но не гарантировано."""
    amount = max(100_000, min(p.amount_rub, p.revenue_rub * 3, 5_000_000) // 50_000 * 50_000)
    if p.product == Product.WORKING_CAPITAL:
        amount = max(amount, 500_000)
    return replace(
        p,
        product=Product.WORKING_CAPITAL if p.product == Product.CREDIT_LINE else p.product,
        amount_rub=amount,
        age_months=max(p.age_months, 40),
        tenure_months=max(p.tenure_months, 12),
        history_months=30,
        closed_obligations=2,
        monthly_payments_rub=min(p.monthly_payments_rub, 20_000),
        overdue_days=0,
        inquiries=0,
        rejected=0,
        restructurings=0,
        tax_debt_rub=0,
        collateral_rub=0,
        guarantor=False,
        term_months=max(p.term_months, 12),
    )


def healthy_params() -> st.SearchStrategy[RequestParams]:
    return request_params().map(healthy)
