"""T-125: ЕИС, налоговые флаги и связанная с АБС блокировка счёта."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.common.inn import generate_inn
from app.common.reldate import resolve
from app.roles.scenarios.identity_people import rng_for, synthetic_inn
from app.roles.scenarios.schemas import ScenarioSpec
from app.roles.tax.schemas import Contract


def _day(value: str | None, default: str, today: date) -> date:
    text = value or default
    if text.startswith(("+", "-")):
        return resolve(text, today)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Неверная дата контракта {text!r}") from exc


def add_contracts(spec: ScenarioSpec, result: dict[str, Any], code: str, today: date) -> None:
    contracts = []
    used: set[str] = set()
    for index, requested in enumerate(spec.contracts):
        rng = rng_for(code, f"contract:{index}")
        # Номер реестра 19 цифр; синтетические 00, год и 13 случайных цифр.
        number = f"00{today.year:04}{rng.randrange(10**13):013}"
        while number in used:
            number = f"00{today.year:04}{rng.randrange(10**13):013}"
        used.add(number)
        status = requested.status or "IN_PROGRESS"
        finished = status in ("EXECUTED", "TERMINATED")
        contract = Contract.model_validate(
            {
                "registryNumber": number,
                "customer": {
                    "name": requested.customer.name,
                    "inn": synthetic_inn(requested.customer.inn, individual=False)
                    if requested.customer.inn
                    else generate_inn(rng),
                },
                "subject": requested.subject,
                "priceRub": requested.price_rub,
                "concludedAt": _day(requested.concluded, "-2M", today),
                "executionDeadline": _day(
                    requested.execution_in, "-1M" if finished else "+3M", today
                ),
                "paymentDeadline": _day(requested.payment_in, "-1M" if finished else "+4M", today),
                "status": status,
                "paidRub": requested.paid_rub
                if requested.paid_rub is not None
                else (requested.price_rub if status == "EXECUTED" else 0),
            }
        )
        contracts.append(contract.model_dump(mode="json", by_alias=True))
    if spec.contracts:
        result.setdefault("tax", {})["contracts"] = contracts


def add_tax(spec: ScenarioSpec, result: dict[str, Any], code: str, today: date, bik: str) -> None:
    requested = spec.tax
    if requested is None:
        return
    tax = result.setdefault("tax", {})
    profile = tax.get("taxProfile")
    fields = (
        requested.tax_debt_rub,
        requested.mass_address,
        requested.mass_director,
        requested.disqualified_management,
    )
    if profile is None and any(value is not None for value in fields):
        if result["identity"]["form"] == "SELF_EMPLOYED":
            raise ValueError("У самозанятого только статус НПД, налогового профиля бизнеса нет")
        profile = {
            "inn": result["identity"]["inn"],
            "debts": {
                "asOf": today.replace(day=1).isoformat(),
                "taxDebtRub": 0,
                "penaltiesRub": 0,
                "finesRub": 0,
            },
            "riskFlags": {},
        }
        tax["taxProfile"] = profile
    if profile is not None:
        if requested.tax_debt_rub is not None:
            profile["debts"]["taxDebtRub"] = requested.tax_debt_rub
        flags = profile.setdefault("riskFlags", {})
        for source, target in (
            ("mass_address", "massAddress"),
            ("mass_director", "massDirector"),
            ("disqualified_management", "disqualifiedManagement"),
        ):
            value = getattr(requested, source)
            if value is not None:
                flags[target] = value
    if requested.account_blocked is None:
        return
    bank = result.setdefault("bankCore", {})
    accounts = bank.get("accounts", [])
    ours = tax.setdefault("accountBlocks", [])
    # Решения другого банка не зависят от состояния нашего счёта.
    tax["accountBlocks"] = [x for x in ours if x["bik"] != bik or x.get("liftedAt")]
    if not requested.account_blocked:
        for account in accounts:
            if account["status"] == "BLOCKED":
                account["status"] = "OPEN"
        return
    if (
        bank.get("customer") is None
        or not accounts
        or not any(a["status"] != "CLOSED" for a in accounts)
    ):
        raise ValueError("tax.accountBlocked: нужен клиент банка с действующим расчётным счётом")
    if len(bik) != 9 or not bik.isdigit():
        raise ValueError("bank_bik должен состоять из девяти цифр")
    for account in accounts:
        if account["status"] != "CLOSED":
            account["status"] = "BLOCKED"
    tax["accountBlocks"].append(
        {
            "number": str(rng_for(code, "account-block").randint(10000, 99999)),
            "date": today.isoformat(),
            "taxAuthorityCode": result["identity"]["inn"][:4],
            "bik": bik,
            "reason": "TAX_DEBT_COLLECTION" if requested.tax_debt_rub else "OTHER",
            "liftedAt": None,
        }
    )
