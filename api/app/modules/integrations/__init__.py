"""Адаптеры к мокам: таймауты, повторы, предохранитель, кэш автозаполнения, журнал вызовов. Документ: 50-08.

Публичный интерфейс модуля — только то, что ниже. Другие модули берут порты через
`get_integrations()` и работают с результатами `Ok` / `SourceUnavailable`.
"""

from app.modules.integrations import (
    reset,  # noqa: F401 — регистрирует сброс демо-данных (T-371)
    scenarios,
)
from app.modules.integrations.bank_core import (
    BankAccount,
    BankCoreReadAdapter,
    ComplianceResult,
    Customer,
    OurLoan,
    ScreeningResult,
    ScreeningSubject,
    Turnover,
    TurnoverMonth,
)
from app.modules.integrations.bank_core_write import (
    BankCoreWriteAdapter,
    Disbursed,
    DisbursementRequest,
    Failure,
    OpenedAccount,
    classify_failure,
)
from app.modules.integrations.breaker import BreakerState, CircuitBreaker, NullBreaker, Permit
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.credit_bureau import (
    BkiConsent,
    BureauEvent,
    BureauEventType,
    BureauSubject,
    CreditBureauAdapter,
    CreditHistory,
    EventApplication,
    EventObligation,
    SubmissionReceipt,
    report_idempotency_key,
    submission_idempotency_key,
)
from app.modules.integrations.journal import CallJournal, CallRecord, DbCallJournal
from app.modules.integrations.models import IntegrationCall
from app.modules.integrations.policy import CallPolicy
from app.modules.integrations.registry import (
    BankruptcyCase,
    CompanyRecord,
    PersonRoles,
    RegistryAdapter,
)
from app.modules.integrations.results import (
    Ok,
    Reason,
    Result,
    SnapshotMeta,
    SourceUnavailable,
    System,
)
from app.modules.integrations.snapshots import known_resources, parse_snapshot
from app.modules.integrations.tax import (
    AccountBlock,
    Financials,
    GovContract,
    SelfEmployedStatus,
    SmeStatus,
    TaxAdapter,
    TaxProfile,
)
from app.modules.integrations.wiring import (
    Integrations,
    build_integrations,
    get_integrations,
    set_integrations,
)

__all__ = [
    "AccountBlock",
    "BankAccount",
    "BankCoreReadAdapter",
    "BankCoreWriteAdapter",
    "BankruptcyCase",
    "BkiConsent",
    "BreakerState",
    "BureauEvent",
    "BureauEventType",
    "BureauSubject",
    "CallJournal",
    "CallPolicy",
    "CallRecord",
    "CircuitBreaker",
    "CompanyRecord",
    "ComplianceResult",
    "CreditBureauAdapter",
    "CreditHistory",
    "Customer",
    "Disbursed",
    "DisbursementRequest",
    "DbCallJournal",
    "EventApplication",
    "EventObligation",
    "Failure",
    "Financials",
    "GovContract",
    "IntegrationCall",
    "IntegrationClient",
    "Integrations",
    "NullBreaker",
    "Ok",
    "OpenedAccount",
    "OurLoan",
    "Permit",
    "PersonRoles",
    "Reason",
    "RegistryAdapter",
    "Result",
    "ScreeningResult",
    "ScreeningSubject",
    "SelfEmployedStatus",
    "SmeStatus",
    "SnapshotMeta",
    "SourceUnavailable",
    "SubmissionReceipt",
    "System",
    "TaxAdapter",
    "TaxProfile",
    "Turnover",
    "TurnoverMonth",
    "build_integrations",
    "classify_failure",
    "get_integrations",
    "known_resources",
    "parse_snapshot",
    "report_idempotency_key",
    "scenarios",
    "set_integrations",
    "submission_idempotency_key",
]
