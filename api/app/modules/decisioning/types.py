"""Типы входа и выхода ядра (T-280, 30-01).

Всё неизменяемое и без `float`: деньги — целые рубли (`int`), доли и ставки — `Decimal`.
Вход целиком сериализуется в JSON и обратно без потерь (`serialization.py`), потому что он
хранится в `decisions.inputs` и нужен для воспроизведения решения (30-13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.modules.decisioning.policy import Policy

# ---------------------------------------------------------------- перечисления


class Product(StrEnum):
    EXPRESS = "EXPRESS"
    WORKING_CAPITAL = "WORKING_CAPITAL"
    CONTRACT = "CONTRACT"
    CREDIT_LINE = "CREDIT_LINE"
    OVERDRAFT = "OVERDRAFT"
    INVESTMENT = "INVESTMENT"


class Mode(StrEnum):
    PREVIEW = "PREVIEW"
    DECISION = "DECISION"


class SourceStatus(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_REQUESTED = "NOT_REQUESTED"


class ApplicantKind(StrEnum):
    LEGAL_ENTITY = "LEGAL_ENTITY"
    INDIVIDUAL_ENTREPRENEUR = "INDIVIDUAL_ENTREPRENEUR"


class SubjectRole(StrEnum):
    """Участник заявки. Для ИП `COMPANY` — сам предприниматель как человек."""

    COMPANY = "COMPANY"
    DIRECTOR = "DIRECTOR"
    FOUNDER = "FOUNDER"
    GUARANTOR = "GUARANTOR"


class Outcome(StrEnum):
    APPROVED = "APPROVED"
    COUNTER_OFFER = "COUNTER_OFFER"
    NEEDS_INFO = "NEEDS_INFO"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    REJECTED = "REJECTED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class Route(StrEnum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class Level(StrEnum):
    L0 = "L0"  # автомат
    L1 = "L1"  # андеррайтер
    L2 = "L2"  # старший андеррайтер


class Grade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class ReasonKind(StrEnum):
    STOP = "STOP"
    FLAG = "FLAG"
    CONSTRAINT = "CONSTRAINT"
    PRODUCT = "PRODUCT"
    ROUTE = "ROUTE"
    DATA = "DATA"
    OUT = "OUT"
    FACTOR = "FACTOR"


class Quality(StrEnum):
    """Качество источника признака (30-02)."""

    OWN_BANK = "OWN_BANK"
    OFFICIAL = "OFFICIAL"
    CLIENT_UPLOAD = "CLIENT_UPLOAD"
    ESTIMATE = "ESTIMATE"


# ---------------------------------------------------------------- вход: заявка и контекст

ParamValue = str | int | bool | Decimal | None


@dataclass(frozen=True, slots=True)
class Collateral:
    description: str
    value_rub: int


@dataclass(frozen=True, slots=True)
class Guarantor:
    inn: str
    consent_signed: bool


@dataclass(frozen=True, slots=True)
class Application:
    application_id: str
    product: Product
    amount_rub: int
    term_months: int
    collateral: Collateral | None = None
    guarantor: Guarantor | None = None
    contract_registry_number: str | None = None
    declared_monthly_revenue_rub: int | None = None
    director_name_in_form: str | None = None
    # Что не заполнено в анкете и какие согласия не подписаны — отвечает pipeline (шаг 1)
    missing_fields: tuple[str, ...] = ()
    unsigned_consents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Context:
    app_today: date
    mode: Mode = Mode.DECISION
    # Номера других заявок компании в работе (SUBMITTED…DISBURSING)
    other_active_applications: tuple[str, ...] = ()
    # Вероятность дефолта за 12 мес. из имитатора (30-19), если считалась; иначе None (T-315)
    p_def12: Decimal | None = None


# ---------------------------------------------------------------- вход: снимок данных


@dataclass(frozen=True, slots=True)
class SourceMeta:
    status: SourceStatus = SourceStatus.OK
    data_as_of: date | None = None
    snapshot_id: str | None = None


@dataclass(frozen=True, slots=True)
class Founder:
    name: str
    inn: str
    share_percent: Decimal
    is_person: bool = True


@dataclass(frozen=True, slots=True)
class RegistryData:
    meta: SourceMeta = field(default_factory=SourceMeta)
    kind: ApplicantKind | None = None
    inn: str = ""
    registration_date: date | None = None
    status_code: str = "ACTIVE"
    okved_main: str = ""
    director_name: str | None = None
    director_inn: str | None = None
    founders: tuple[Founder, ...] = ()


@dataclass(frozen=True, slots=True)
class NpdData:
    meta: SourceMeta = field(default_factory=SourceMeta)
    is_self_employed: bool = False


@dataclass(frozen=True, slots=True)
class BankruptcyCase:
    case_number: str
    stage: str  # OBSERVATION | RESTRUCTURING | PROPERTY_REALIZATION | COMPLETED
    started_at: date
    completed_at: date | None = None


@dataclass(frozen=True, slots=True)
class BankruptcyCheck:
    """Ответ ЕФРСБ по одному участнику."""

    inn: str
    role: SubjectRole
    share_percent: Decimal | None = None  # у учредителей-людей
    meta: SourceMeta = field(default_factory=SourceMeta)
    cases: tuple[BankruptcyCase, ...] = ()


@dataclass(frozen=True, slots=True)
class TaxData:
    meta: SourceMeta = field(default_factory=SourceMeta)
    regimes: tuple[str, ...] = ()
    tax_debt_rub: int = 0
    penalties_rub: int = 0
    fines_rub: int = 0
    offenses_count: int = 0
    mass_address: bool = False
    mass_director: bool = False
    mass_founder: bool = False
    account_block_active: bool = False
    sme_category: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialYear:
    year: int
    revenue_rub: int  # строка 2110
    net_profit_rub: int  # 2400
    interest_paid_rub: int  # 2330


@dataclass(frozen=True, slots=True)
class FinancialsData:
    meta: SourceMeta = field(default_factory=lambda: SourceMeta(SourceStatus.NOT_FOUND))
    years: tuple[FinancialYear, ...] = ()  # от нового к старому


@dataclass(frozen=True, slots=True)
class ContractInfo:
    registry_number: str
    price_rub: int
    paid_rub: int
    status: str  # IN_PROGRESS | EXECUTED | TERMINATED
    payment_deadline: date


@dataclass(frozen=True, slots=True)
class ContractsData:
    meta: SourceMeta = field(default_factory=lambda: SourceMeta(SourceStatus.NOT_REQUESTED))
    contracts: tuple[ContractInfo, ...] = ()


@dataclass(frozen=True, slots=True)
class ComplianceResult:
    inn: str
    role: SubjectRole
    aml_listed: bool = False


@dataclass(frozen=True, slots=True)
class ComplianceData:
    meta: SourceMeta = field(default_factory=SourceMeta)
    results: tuple[ComplianceResult, ...] = ()


@dataclass(frozen=True, slots=True)
class OurLoan:
    contract_uid: str
    monthly_payment_rub: int
    balance_rub: int


@dataclass(frozen=True, slots=True)
class CustomerData:
    meta: SourceMeta = field(default_factory=lambda: SourceMeta(SourceStatus.NOT_FOUND))
    is_customer: bool = False
    customer_since: date | None = None
    our_loans: tuple[OurLoan, ...] = ()


@dataclass(frozen=True, slots=True)
class TurnoverMonth:
    month: date  # первое число месяца
    incoming_net_rub: int
    outgoing_rub: int
    counterparties_in: int | None = None


@dataclass(frozen=True, slots=True)
class TurnoverData:
    meta: SourceMeta = field(default_factory=lambda: SourceMeta(SourceStatus.NOT_FOUND))
    months: tuple[TurnoverMonth, ...] = ()  # от старого к новому


@dataclass(frozen=True, slots=True)
class StatementData:
    """Разобранная выписка клиента из другого банка (CLIENT_UPLOAD)."""

    meta: SourceMeta = field(default_factory=lambda: SourceMeta(SourceStatus.NOT_REQUESTED))
    months: tuple[TurnoverMonth, ...] = ()
    owner_inn_matches: bool = True


@dataclass(frozen=True, slots=True)
class BkiObligation:
    uid: str
    kind: str
    status: str = "ACTIVE"
    monthly_payment_rub: int = 0
    balance_rub: int = 0


@dataclass(frozen=True, slots=True)
class BkiReport:
    has_history: bool = False
    history_months: int = 0
    active_obligations: int = 0
    closed_obligations: int = 0
    total_debt_rub: int = 0
    monthly_payments_rub: int = 0
    contingent_liabilities_rub: int = 0
    current_overdue_rub: int = 0
    current_overdue_days: int = 0
    max_overdue_days_24m: int = 0
    restructurings_24m: int = 0
    inquiries_30d_excl_own: int = 0
    rejected_90d_excl_own: int = 0
    obligations: tuple[BkiObligation, ...] = ()
    bankruptcies: tuple[BankruptcyCase, ...] = ()


@dataclass(frozen=True, slots=True)
class BkiSubject:
    role: SubjectRole
    inn: str
    meta: SourceMeta = field(default_factory=SourceMeta)
    report: BkiReport | None = None  # None при NOT_FOUND / UNAVAILABLE / NOT_REQUESTED


@dataclass(frozen=True, slots=True)
class Snapshot:
    registry: RegistryData = field(default_factory=RegistryData)
    npd: NpdData = field(default_factory=lambda: NpdData(SourceMeta(SourceStatus.NOT_REQUESTED)))
    bankruptcies: tuple[BankruptcyCheck, ...] = ()
    tax: TaxData = field(default_factory=TaxData)
    financials: FinancialsData = field(default_factory=FinancialsData)
    contracts: ContractsData = field(default_factory=ContractsData)
    compliance: ComplianceData = field(default_factory=ComplianceData)
    customer: CustomerData = field(default_factory=CustomerData)
    turnover: TurnoverData = field(default_factory=TurnoverData)
    statement: StatementData = field(default_factory=StatementData)
    bki: tuple[BkiSubject, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionInput:
    application: Application
    snapshot: Snapshot
    context: Context
    policy: Policy

    @property
    def application_id(self) -> str:
        return self.application.application_id


# ---------------------------------------------------------------- выход


@dataclass(frozen=True, slots=True)
class ReasonCode:
    code: str
    kind: ReasonKind
    params: dict[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Explanation:
    """Тексты по одному коду (30-12): клиенту, андеррайтеру, «что можно сделать»."""

    code: str
    client: str
    underwriter: str
    action: str


@dataclass(frozen=True, slots=True)
class FactorScore:
    factor: str
    value: str
    points: int
    max_points: int

    @property
    def deficit(self) -> int:
        return self.max_points - self.points


@dataclass(frozen=True, slots=True)
class RateBreakdown:
    key_rate: Decimal
    spread: Decimal
    expected_loss: Decimal
    expenses: Decimal
    capital_charge: Decimal
    raw_rate: Decimal
    rate: Decimal  # после округления и коридора
    lgd: Decimal
    pd: Decimal
    corridor_min: Decimal
    corridor_max: Decimal
    rate_with_collateral: Decimal | None = None  # подсказка «с залогом было бы…»


@dataclass(frozen=True, slots=True)
class Comparison:
    """Сверка двух чисел (30-02): `|A − B| / B`, знаменатель B — отчётность или расчёт."""

    a_rub: int
    b_rub: int
    deviation: Decimal
    year: int | None = None  # календарный год сверки; `None` у заявленной выручки


@dataclass(frozen=True, slots=True)
class PumpStat:
    """Накачка оборотов (30-02): `x` — среднее последних месяцев, `b` — медиана базы перед ними."""

    recent_rub: int
    base_rub: int
    ratio: Decimal
    modified_z: Decimal
    # `x / b` того же окна годом ранее; `None`, если ряд короче 24 мес. (сезонное исключение)
    prior_year_ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class Features:
    """Признаки шага 6 (30-02). `None` — «нет данных», а не ноль."""

    business_age_months: int | None
    is_bank_customer: bool
    customer_tenure_months: int | None
    industry_group: str
    revenue_source: str | None  # OWN_BANK | OFFICIAL | CLIENT_UPLOAD | None
    revenue_quality: Quality | None
    revenue_months: int
    revenue_cautious_rub: int | None
    revenue_annual_rub: int | None
    flow_model_rub: int | None
    flow_quality: Quality | None
    flow_observed_rub: int | None
    inflow_average_rub: int | None
    flow_crosscheck_ratio: Decimal | None
    existing_payments_rub: int
    total_debt_rub: int
    debt_to_revenue: Decimal | None
    coverage_existing: Decimal | None
    revenue_trend_pct: Decimal | None
    revenue_cv: Decimal | None
    bad_months: int | None
    is_seasonal: bool
    stress_shock: Decimal
    credit_history_class: str
    max_overdue_24m_days: int
    restructurings_24m: int
    inquiries_30d: int
    rejected_90d: int
    bki_known: bool
    tax_debt_rub: int
    tax_penalties_rub: int
    tax_debt_ratio: Decimal | None
    tax_offenses: int
    account_block_active: bool
    tax_known: bool
    net_profit_rub: int | None
    interest_paid_rub: int | None
    collateral_provided: bool
    guarantor_confirmed: bool
    security_confirmed: bool
    form_matches_registry: bool
    # Сверка и антифрод (T-288): `None` — данных для проверки нет
    mismatch_turnover_fin: Comparison | None
    mismatch_declared: Comparison | None
    mismatch_statement: Comparison | None
    pump: PumpStat | None
    transit_months: int | None
    payers_in_6m_max: int | None
    payers_in_6m_avg_income_rub: int | None
    risk_mass_address: bool
    risk_mass_director: bool
    risk_mass_founder: bool


@dataclass(frozen=True, slots=True)
class Numbers:
    """Числа решения (30-01). Пусто, если шаг не выполнялся."""

    revenue_cautious_rub: int | None = None
    revenue_annual_rub: int | None = None
    flow_rub: int | None = None
    existing_payments_rub: int | None = None
    score_points: int | None = None
    grade: Grade | None = None
    pd: Decimal | None = None
    factors: tuple[FactorScore, ...] = ()
    rate: Decimal | None = None
    rate_breakdown: RateBreakdown | None = None
    payment_rub: int | None = None
    last_payment_rub: int | None = None
    overpayment_rub: int | None = None
    dscr: Decimal | None = None
    stress_dscr: Decimal | None = None
    stress_shock: Decimal | None = None
    debt_to_revenue_with_new: Decimal | None = None
    p_max_rub: int | None = None
    max_amount_formula_rub: int | None = None
    max_amount_rub: int | None = None
    max_amount_by_term: tuple[tuple[int, int], ...] = ()
    min_term_months: int | None = None
    auto_limit_rub: int | None = None
    p_def12: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Variant:
    """Встречное предложение (T-297; здесь только условное для молодого бизнеса)."""

    kind: str
    product: Product
    amount_rub: int
    term_months: int
    rate: Decimal
    payment_rub: int
    dscr: Decimal
    stress_dscr: Decimal
    security_required: bool = False
    recommended: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Для `MANUAL_REVIEW`: что решило бы ядро без ручных триггеров (30-11)."""

    outcome: Outcome
    hint: str = ""


@dataclass(frozen=True, slots=True)
class TraceStep:
    step: str
    executed: bool
    detail: dict[str, ParamValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionResult:
    outcome: Outcome
    route: Route
    required_level: Level
    reasons: tuple[ReasonCode, ...]
    numbers: Numbers
    features: Features | None
    variants: tuple[Variant, ...]
    # Пока оптимизатор встречных не готов (T-297), здесь `PLACEHOLDER_T297`
    variants_status: str
    recommendation: Recommendation | None
    explanations: tuple[Explanation, ...]
    trace: tuple[TraceStep, ...]
    inputs_hash: str
    policy_version: int
    policy_hash: str
    mode: Mode
    kind: str = "FINAL"

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.reasons)

    @property
    def primary_reason(self) -> str | None:
        return self.reasons[0].code if self.reasons else None
