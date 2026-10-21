"""Чистое разворачивание базовой истории БКИ (T-123).

Вход — уже объединённый с пресетом ScenarioSpec и identity из T-120.
Выход bki[]: {inn, body} для админ-PUT БКИ, bankLoans[]: {inn, body:{loans:[]}}
для дополнения bank-core данными T-125. NOT_FOUND представлен отсутствием субъекта.
Просрочки, запросы, отказы и реструктуризации — T-124. Банкротства добавляет T-125.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.common.reldate import add_months
from app.roles.scenarios.bki_events import apply_events, overdue_start
from app.roles.scenarios.bki_loans import DEFAULTS, CreditDefaults, active_loan, closed_loan
from app.roles.scenarios.schemas import ActiveLoan, BkiSubjectSpec, ClosedLoan, ScenarioSpec


def merge_subjects(spec: ScenarioSpec, identity: dict[str, Any]) -> dict[str, BkiSubjectSpec]:
    """Одинаковый ИНН — один субъект, совпадающие поля не удваивают обязательства."""
    merged: dict[str, dict[str, Any]] = {}
    if spec.bki is None:
        return {}
    for role in ("company", "director", "owner"):
        block = getattr(spec.bki, role)
        if block is None:
            continue
        inn = identity["subjectRefs"].get(role)
        if inn is None:
            raise ValueError(f"bki.{role}: у этой формы нет такого субъекта")
        raw = block.model_dump(exclude_none=True)
        target = merged.setdefault(inn, {})
        for key, value in raw.items():
            if key in target and target[key] != value:
                raise ValueError(f"Блоки БКИ одного ИНН противоречат друг другу: {key}")
            target[key] = value
    return {inn: BkiSubjectSpec.model_validate(raw) for inn, raw in merged.items()}


def _subject(identity: dict[str, Any], inn: str) -> dict[str, Any]:
    if inn == identity["inn"] and identity["form"] in {"LLC", "JSC"}:
        return {
            "type": "LEGAL_ENTITY",
            "inn": inn,
            "ogrn": identity["ogrn"],
            "name": identity["shortName"],
        }
    person = next((p for p in identity["persons"] if p["inn"] == inn), None)
    if person is None:
        raise ValueError(f"В identity нет человека с ИНН {inn}")
    return {
        "type": "PERSON",
        **{key: person[key] for key in ("inn", "lastName", "firstName", "middleName", "birthDate")},
    }


def expand_bki(
    spec: ScenarioSpec,
    identity: dict[str, Any],
    code: str,
    today: date,
    *,
    defaults: CreditDefaults = DEFAULTS,
) -> dict[str, Any]:
    subjects = merge_subjects(spec, identity)
    bki, bank_loans = [], []
    for inn, block in subjects.items():
        loans = list(block.active_loans or [])
        if block.monthly_payments_rub is not None:
            if loans:
                raise ValueError("Укажите activeLoans или monthlyPaymentsRub, а не оба")
            if block.monthly_payments_rub:
                loans = [ActiveLoan(kind="LOAN", monthly_payment_rub=block.monthly_payments_rub)]
        if block.history_years == 0:
            if (
                loans
                or block.closed_loans
                or any(
                    (
                        block.current_overdue_days,
                        block.current_overdue_rub,
                        block.past_max_overdue_days,
                        block.restructurings24m,
                        block.sold_to_collectors,
                        block.inquiries30d,
                        block.rejected_applications90d,
                    )
                )
            ):
                raise ValueError("historyYears: 0 несовместим с кредитами")
            continue
        # У организации нет истории до регистрации. У ИП это личная история человека.
        earliest = (
            date.fromisoformat(identity["registrationDate"])
            if inn == identity["inn"] and identity["form"] in {"LLC", "JSC"}
            else None
        )
        since = overdue_start(block, today)
        obligations, our_loans = [], []
        for index, loan in enumerate(loans):
            if loan.our_bank and (inn != identity["inn"] or identity["form"] == "SELF_EMPLOYED"):
                raise ValueError("ourBank доступен только для компании или ИП, не для физлица")
            if loan.our_bank and not (spec.bank and spec.bank.is_customer):
                raise ValueError("Для ourBank нужен bank.isCustomer: true")
            obligation, bank_loan = active_loan(
                loan, code, inn, index, today, earliest, defaults, since if index == 0 else None
            )
            obligations.append(obligation)
            if bank_loan:
                our_loans.append(bank_loan)
        for index, finished in enumerate(block.closed_loans or []):
            obligations.append(
                closed_loan(finished, code, inn, f"closed-{index}", today, earliest, defaults)
            )
        if block.history_years:
            months = int(
                (Decimal(str(block.history_years)) * 12).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
            )
            history_start = add_months(today, -months)
            if earliest is not None:
                history_start = max(history_start, earliest)
            first_opened = min(
                (date.fromisoformat(o["openedAt"]) for o in obligations), default=today
            )
            if history_start < first_opened:
                closed_at = min(add_months(history_start, 24), today - timedelta(days=1))
                if history_start < closed_at:
                    generated = ClosedLoan(
                        kind="LOAN",
                        amount_rub=100000,
                        opened_at=history_start.isoformat(),
                        closed_at=closed_at.isoformat(),
                    )
                    obligations.append(
                        closed_loan(generated, code, inn, "history", today, earliest, defaults)
                    )
        inquiries, applications = apply_events(
            block, obligations, code, inn, today, earliest, defaults
        )
        bki.append(
            {
                "inn": inn,
                "body": {
                    "subject": _subject(identity, inn),
                    "obligations": obligations,
                    "inquiries": inquiries,
                    "applications": applications,
                    "bankruptcies": [],
                },
            }
        )
        if our_loans:
            bank_loans.append({"inn": inn, "body": {"loans": our_loans}})
    return {"bki": bki, "bankLoans": bank_loans}
