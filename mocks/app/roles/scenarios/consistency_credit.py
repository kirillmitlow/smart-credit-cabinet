"""Кредиты, дела, блокировки и контракты: сверка окончательных тел моков."""

from typing import Any

from app.roles.scenarios.consistency_common import Context, require
from app.roles.scenarios.credit_uid import uid_is_valid


def loan_uids(c: Context) -> None:
    seen: set[str] = set()
    for entry in c.data["bki"]:
        for loan in entry["body"]["obligations"]:
            uid = loan["uid"]
            require(uid_is_valid(uid), f"УИд {uid}: нужен UUID и верный контрольный символ")
            require(uid.lower() not in seen, f"УИд {uid} повторяется у разных обязательств")
            seen.add(uid.lower())


def loan_payment(c: Context) -> None:
    for entry in c.data["bki"]:
        for loan in entry["body"]["obligations"]:
            amount = loan["amountRub"] if loan["amountRub"] is not None else loan["limitRub"]
            require(
                amount is not None and amount >= 0, f"Кредит {loan['uid']}: нужна сумма или лимит"
            )
            payment, balance = loan["monthlyPaymentRub"] or 0, loan["balanceRub"]
            require(
                0 <= payment <= amount,
                f"Кредит {loan['uid']}: платёж {payment} вне диапазона 0…{amount}",
            )
            require(
                0 <= balance <= amount,
                f"Кредит {loan['uid']}: остаток {balance} вне диапазона 0…{amount}",
            )
            require(loan["overdueRub"] >= 0, f"Кредит {loan['uid']}: отрицательная просрочка")


def loan_dates(c: Context) -> None:
    for entry in c.data["bki"]:
        for loan in entry["body"]["obligations"]:
            opened, closed = loan["openedAt"], loan["closedAt"]
            require(
                opened <= c.today.isoformat(), f"Кредит {loan['uid']} открыт в будущем {opened}"
            )
            if loan["plannedCloseAt"]:
                require(
                    loan["plannedCloseAt"] > opened,
                    f"Кредит {loan['uid']}: плановое закрытие не позже открытия",
                )
            if closed:
                require(
                    opened < closed <= c.today.isoformat() and loan["balanceRub"] == 0,
                    f"Закрытый кредит {loan['uid']}: нужны даты открытия < закрытия ≤ сегодня и нулевой остаток",
                )
            require(
                loan["status"] != "CLOSED" or closed is not None,
                f"Кредит {loan['uid']}: статус CLOSED требует closedAt",
            )
            for period in loan["overduePeriods"]:
                require(
                    closed is None or period["until"] is not None,
                    f"Кредит {loan['uid']}: у закрытого кредита не может быть текущей просрочки",
                )
                require(
                    period["since"] >= opened,
                    f"Кредит {loan['uid']}: просрочка {period['since']} раньше открытия {opened}",
                )
                require(
                    period["since"] <= c.today.isoformat(),
                    f"Кредит {loan['uid']}: просрочка в будущем",
                )
                if period["until"]:
                    require(
                        period["until"] <= (closed or c.today.isoformat()),
                        f"Кредит {loan['uid']}: просрочка после закрытия/сегодня",
                    )


def bankruptcy_match(c: Context) -> None:
    keys = ("caseNumber", "stage", "startedAt", "completedAt")
    registry = {
        (r["subjectInn"], *(r[k] for k in keys)) for r in c.data["registry"]["bankruptcies"]
    }
    bki = {
        (entry["inn"], *(r[k] for k in keys))
        for entry in c.data["bki"]
        for r in entry["body"]["bankruptcies"]
    }
    require(
        registry == bki,
        f"Дела ЕФРСБ и БКИ не совпадают: только ЕФРСБ={registry - bki}, только БКИ={bki - registry}",
    )


def bankrupt_status(c: Context) -> None:
    entity = c.data["registry"]["entity"]
    if entity is None:
        return
    ongoing = any(
        r["subjectInn"] == c.identity["inn"] and r["completedAt"] is None
        for r in c.data["registry"]["bankruptcies"]
    )
    require(
        (entity["status"]["code"] == "BANKRUPT") == ongoing,
        f"Статус {entity['status']['code']}, незавершённое дело компании={ongoing}",
    )


def bankruptcy_dates(c: Context) -> None:
    for case in c.data["registry"]["bankruptcies"]:
        require(
            case["startedAt"] <= c.today.isoformat(), f"Дело {case['caseNumber']}: начало в будущем"
        )
        require(
            case["completedAt"] is None or case["completedAt"] <= c.today.isoformat(),
            f"Дело {case['caseNumber']}: завершение в будущем",
        )


def our_bank_uid(c: Context) -> None:
    company: dict[str, Any] = next(
        (x["body"] for x in c.data["bki"] if x["inn"] == c.identity["inn"]), {}
    )
    bki = {loan["uid"]: loan for loan in company.get("obligations", [])}
    bank = {loan["contractUid"]: loan for loan in c.bank["loans"]}
    expected = {
        loan["contractUid"]
        for entry in c.data.get("bankLoans", [])
        for loan in entry["body"]["loans"]
    }
    require(set(bank) == expected, f"Кредиты нашего банка: УИд {set(bank)}, ожидались {expected}")
    for uid, loan in bank.items():
        require(uid in bki, f"Кредит АБС {uid} отсутствует в БКИ")
        obligation = bki[uid]
        source = next(
            x
            for entry in c.data["bankLoans"]
            for x in entry["body"]["loans"]
            if x["contractUid"] == uid
        )
        require(
            all(
                loan[key] == source[key]
                for key in (
                    "kind",
                    "amountRub",
                    "limitRub",
                    "termMonths",
                    "ratePercent",
                    "repaymentType",
                    "disbursedAt",
                )
            ),
            f"Кредит {uid}: условия АБС отличаются от параметров ourBank",
        )
        history = c.history.get(uid)
        if history is not None:
            require(
                all(
                    obligation[key] == history.body[key]
                    for key in ("balanceRub", "monthlyPaymentRub")
                ),
                f"Кредит {uid}: остаток/платёж нашего банка должны совпадать с графиком",
            )
        require(
            loan["amountRub"]
            == (
                obligation["amountRub"]
                if obligation["amountRub"] is not None
                else obligation["balanceRub"]
            ),
            f"Кредит {uid}: сумма АБС расходится с БКИ",
        )
        require(
            loan["kind"] == obligation["kind"] and loan["disbursedAt"] == obligation["openedAt"],
            f"Кредит {uid}: вид/дата выдачи различаются между БКИ и АБС",
        )


def account_block(c: Context) -> None:
    decision = any(
        r["bik"] == c.settings.bank_bik and r["liftedAt"] is None for r in c.tax["accountBlocks"]
    )
    blocked = any(
        a["type"] == "SETTLEMENT" and a["status"] == "BLOCKED" for a in c.bank["accounts"]
    )
    require(
        decision == blocked,
        f"Блокировка налоговой с БИК {c.settings.bank_bik}={decision}, счёт BLOCKED={blocked}",
    )


def contracts(c: Context) -> None:
    for contract in c.tax["contracts"]:
        require(
            contract["executionDeadline"] >= contract["concludedAt"]
            and contract["paymentDeadline"] >= contract["concludedAt"],
            f"Контракт {contract['registryNumber']}: срок исполнения/оплаты раньше заключения",
        )
        require(
            contract["paidRub"] <= contract["priceRub"],
            f"Контракт {contract['registryNumber']}: оплачено {contract['paidRub']}, цена {contract['priceRub']}",
        )
