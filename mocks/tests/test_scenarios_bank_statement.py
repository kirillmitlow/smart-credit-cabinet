"""T-130: independent ledger checks and the public admin-only download contract."""

from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.common.accounts import OTHER_BANK_BIK, account_is_valid
from app.common.db import get_session
from app.common.inn import inn_is_valid
from app.main import create_app
from app.roles.scenarios.bank_statement import BankStatementRequest, build_statement
from app.roles.scenarios.builtin import builtin_scenarios
from app.roles.scenarios.expand import expand, resolved_spec
from app.roles.scenarios.models import Scenario
from app.roles.scenarios.schemas import FinanceSpec, ScenarioSpec
from tests.conftest import ADMIN_KEY, API_KEY, make_settings

TODAY = date(2026, 10, 21)
INN = "001298765490"
HEADERS = {"X-Admin-Key": ADMIN_KEY}
GET = "/api/v1/scenarios/garipov/documents/bank-statement"
POST = "/api/v1/documents/bank-statement"


def read_file(content: bytes) -> tuple[dict, dict, list[dict]]:
    """Small independent reader: controls are never calculated by the generator under test."""
    assert content.endswith(b"\r\n")
    assert b"\n" not in content.replace(b"\r\n", b"")
    assert b"\r" not in content.replace(b"\r\n", b"")
    lines = content.decode("cp1251").split("\r\n")
    assert lines[0] == "1CClientBankExchange"
    assert lines[-2:] == ["КонецФайла", ""]
    header: dict = {}
    controls: dict = {}
    payments: list[dict] = []
    target = header
    for line in lines[1:-2]:
        if line == "СекцияРасчСчет":
            target = controls
        elif line.startswith("СекцияДокумент="):
            target = {}
            payments.append(target)
            assert line == "СекцияДокумент=Платежное поручение"
        elif line in ("КонецРасчСчет", "КонецДокумента"):
            target = header
        else:
            key, value = line.split("=", 1)
            assert key not in target
            target[key] = value
    return header, controls, payments


def cents(value: str) -> int:
    amount = Decimal(value) * 100
    assert amount == amount.to_integral_value()
    return int(amount)


def file_date(value: str) -> date:
    day, month, year = map(int, value.split("."))
    return date(year, month, day)


def reconcile(content: bytes, expected_inn: str = INN) -> tuple[dict[str, list[int]], dict]:
    header, controls, payments = read_file(content)
    own = header["РасчСчет"]
    start = file_date(header["ДатаНачала"])
    end = file_date(header["ДатаКонца"])
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    refs = set()
    for payment in payments:
        incoming = payment["ПолучательСчет"] == own
        owner_side = "Получатель" if incoming else "Плательщик"
        assert payment[owner_side + "ИНН"] == expected_inn
        assert payment["Номер"] not in refs
        refs.add(payment["Номер"])
        at = file_date(payment["ДатаПоступило" if incoming else "ДатаСписано"])
        assert start <= at <= end
        assert payment["Дата"] == at.strftime("%d.%m.%Y")
        assert cents(payment["Сумма"]) > 0
        for side in ("Плательщик", "Получатель"):
            assert inn_is_valid(payment[side + "ИНН"])
            assert account_is_valid(OTHER_BANK_BIK, payment[side + "Счет"])
            assert payment[side + "РасчСчет"] == payment[side + "Счет"]
        totals[f"{at:%Y-%m}"][0 if incoming else 1] += cents(payment["Сумма"])
    incoming = sum(x[0] for x in totals.values())
    outgoing = sum(x[1] for x in totals.values())
    assert incoming == cents(controls["ВсегоПоступило"])
    assert outgoing == cents(controls["ВсегоСписано"])
    assert cents(controls["НачальныйОстаток"]) + incoming - outgoing == cents(
        controls["КонечныйОстаток"]
    )
    return dict(totals), controls


def file_for(*, months: int = 12, today: date = TODAY, **changes: Any) -> tuple[bytes, str]:
    parameters = {
        "inn": INN,
        "holder_name": "Гарипов Рустам Ильдарович",
        "okved": "96.02",
        "finance": FinanceSpec(
            avg_monthly_revenue_rub=700000,
            noise_percent=0,
            net_margin_percent=13,
            min_monthly_surplus_rub=100000,
        ),
        "regime": "PSN",
        "code": "garipov",
        "today": today,
        "months": months,
    }
    return build_statement(**(parameters | changes))


def test_garipov_exact_oracle_and_format() -> None:
    content, filename = file_for()
    header, _, payments = read_file(content)
    assert filename == f"statement_{INN}_2025-10_2026-09.txt"
    assert header["Отправитель"] == "Синтетический банк (симуляция)"
    assert header["ВерсияФормата"] == "1.03"
    assert header["Кодировка"] == "Windows"
    with pytest.raises(UnicodeDecodeError):
        content.decode("utf-8")
    totals, controls = reconcile(content)
    assert len(totals) == 12
    assert set(map(tuple, totals.values())) == {(70000000, 60000000)}
    assert cents(controls["НачальныйОстаток"]) == 0
    assert cents(controls["КонечныйОстаток"]) == 120000000
    counts: dict[str, int] = defaultdict(int)
    for row in payments:
        counts[row["Дата"][3:]] += 1
    assert max(counts.values()) <= 60
    assert len(content) < 5 * 1024 * 1024


@pytest.mark.parametrize("months", range(1, 25))
def test_full_month_period_and_determinism(months: int) -> None:
    content, _ = file_for(months=months, today=date(2024, 3, 1))
    assert content == file_for(months=months, today=date(2024, 3, 31))[0]
    header, _, _ = read_file(content)
    assert header["ДатаКонца"] == "29.02.2024"
    assert header["ДатаНачала"].startswith("01.")
    totals, _ = reconcile(content)
    assert len(totals) == months
    assert sum(x[0] for x in totals.values()) == months * 70000000


def test_turnover_overrides_are_authoritative_and_window_invariant() -> None:
    overrides = [{"month": "2026-09", "incomingRub": 123456, "outgoingRub": 98765}]
    a, _ = reconcile(file_for(turnover=overrides)[0])
    b, _ = reconcile(file_for(months=6, turnover=overrides)[0])
    assert a["2026-09"] == [12345600, 9876500]
    assert all(a[key] == value for key, value in b.items())


@pytest.mark.parametrize(
    ("trend", "season"), [("GROWTH", "AGRO"), ("DECLINE", "RETAIL_Q4"), ("STABLE", "NONE")]
)
def test_trend_vat_noise_and_margin_still_reconcile(trend: str, season: str) -> None:
    finance = FinanceSpec.model_validate(
        {
            "avgMonthlyRevenueRub": 900000,
            "noisePercent": 8,
            "revenueTrend": trend,
            "seasonality": season,
            "vatRatePercent": 22,
            "netMarginPercent": -10,
        }
    )
    content, _ = file_for(months=24, finance=finance)
    totals, controls = reconcile(content)
    assert len(totals) == 24
    assert len({x[0] for x in totals.values()}) > 1
    assert cents(controls["НачальныйОстаток"]) > 0
    assert cents(controls["КонечныйОстаток"]) >= 0


@pytest.fixture
def app() -> FastAPI:
    """ASGI routes use real stored-scenario service with a read-only session test double."""
    app = create_app(make_settings(mock_role="scenarios", app_today=TODAY))
    rows = {}
    for code in ("garipov", "sokolova"):
        spec = next(x for x in builtin_scenarios(TODAY) if x.code == code)
        rows[code] = Scenario(
            code=code,
            spec=spec.model_dump(mode="json", by_alias=True),
            expanded=expand(spec, TODAY),
        )
    spec = ScenarioSpec.model_validate(
        {"code": "self", "preset": "SELF_EMPLOYED", "title": "Самозанятый"}
    )
    rows["self"] = Scenario(
        code="self", spec=spec.model_dump(mode="json", by_alias=True), expanded=expand(spec, TODAY)
    )

    class ReadOnlySession:
        async def get(self, model: type, code: str) -> Scenario | None:
            assert model is Scenario
            return rows.get(code)

    async def session() -> AsyncIterator[ReadOnlySession]:
        yield ReadOnlySession()

    app.dependency_overrides[get_session] = session
    return app


async def test_get_real_builtin_spec_and_binary_headers(client: httpx.AsyncClient) -> None:
    first = await client.get(GET, headers=HEADERS)
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "text/plain; charset=windows-1251"
    assert (
        first.headers["content-disposition"]
        == f'attachment; filename="statement_{INN}_2025-10_2026-09.txt"'
    )
    assert first.headers["x-mock-simulated"] == "true"
    assert first.content == (await client.get(GET, headers=HEADERS)).content
    assert set(map(tuple, reconcile(first.content)[0].values())) == {(70000000, 60000000)}


async def test_post_without_database_seed_and_randomness(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    assert app.state.database is None
    body = {"inn": INN, "avgMonthlyRevenueRub": 700000, "seed": 42, "months": 24}
    a = await client.post(POST, headers=HEADERS, json=body)
    assert a.status_code == 200, a.text
    assert a.content == (await client.post(POST, headers=HEADERS, json=body)).content
    reconcile(a.content)
    body.pop("seed")
    a = await client.post(POST, headers=HEADERS, json=body)
    b = await client.post(POST, headers=HEADERS, json=body)
    assert a.status_code == b.status_code == 200
    assert a.content != b.content


async def test_post_legal_holder_and_required_revenue(client: httpx.AsyncClient) -> None:
    body = {
        "inn": "0012345673",
        "avgMonthlyRevenueRub": 1000000,
        "holderName": "ООО «Демо»",
        "seed": 8,
    }
    response = await client.post(POST, headers=HEADERS, json=body)
    assert response.status_code == 200
    reconcile(response.content, body["inn"])
    for missing in ("inn", "avgMonthlyRevenueRub"):
        response = await client.post(
            POST, headers=HEADERS, json={k: v for k, v in body.items() if k != missing}
        )
        assert response.status_code == 422


async def test_zero_turnover_still_has_random_post_and_repeatable_seed(
    client: httpx.AsyncClient,
) -> None:
    body = {"inn": INN, "avgMonthlyRevenueRub": 0}
    first = await client.post(POST, headers=HEADERS, json=body)
    second = await client.post(POST, headers=HEADERS, json=body)
    assert first.status_code == second.status_code == 200
    assert first.content != second.content
    _, controls, payments = read_file(first.content)
    assert payments == []
    assert cents(controls["ВсегоПоступило"]) == cents(controls["ВсегоСписано"]) == 0
    body["seed"] = 0
    first = await client.post(POST, headers=HEADERS, json=body)
    assert first.content == (await client.post(POST, headers=HEADERS, json=body)).content


@pytest.mark.parametrize(
    ("headers", "status"),
    [({}, 401), ({"X-Admin-Key": "wrong"}, 401), ({"X-Api-Key": API_KEY}, 403)],
)
@pytest.mark.parametrize(("method", "path"), [("GET", GET), ("POST", POST)])
async def test_admin_only(
    client: httpx.AsyncClient, headers: dict, status: int, method: str, path: str
) -> None:
    response = await client.request(
        method, path, headers=headers, json={"inn": INN, "avgMonthlyRevenueRub": 700000}
    )
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("months", [0, 25, -1, "oops"])
async def test_invalid_months(client: httpx.AsyncClient, months: int | str) -> None:
    for response in (
        await client.get(GET, headers=HEADERS, params={"months": months}),
        await client.post(
            POST,
            headers=HEADERS,
            json={"inn": INN, "months": months, "avgMonthlyRevenueRub": 700000},
        ),
    ):
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("inn", ["001298765491", "abc", "123", "١٢٣٤٥٦٧٨٩٠"])
async def test_invalid_inn(client: httpx.AsyncClient, inn: str) -> None:
    response = await client.post(
        POST, headers=HEADERS, json={"inn": inn, "avgMonthlyRevenueRub": 700000}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INN_INVALID"


@pytest.mark.parametrize(
    "changes",
    [
        {"avgMonthlyRevenueRub": None},
        {"avgMonthlyRevenueRub": -1},
        {"unknown": True},
        {"holderName": "Банк\r\nСумма=1"},
        {"holderName": "Банк🙂"},
        {"vatRatePercent": 101},
        {"okved": "oops"},
        {"trendPercent": 10},
        {"revenueTrend": "DECLINE", "trendPercent": 100},
        {"minMonthlySurplusRub": 999999999},
    ],
)
async def test_invalid_post_parameters(client: httpx.AsyncClient, changes: dict) -> None:
    response = await client.post(
        POST, headers=HEADERS, json={"inn": INN, "avgMonthlyRevenueRub": 700000} | changes
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_missing_scenario_and_no_business_account(client: httpx.AsyncClient) -> None:
    response = await client.get(GET.replace("garipov", "unknown"), headers=HEADERS)
    assert response.status_code == 404
    assert response.json()["code"] == "SCENARIO_NOT_FOUND"
    response = await client.get(GET.replace("garipov", "self"), headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_openapi_declares_admin_binary_contract(app: FastAPI) -> None:
    schema = app.openapi()
    for method, path in (("get", GET.replace("garipov", "{code}")), ("post", POST)):
        operation = schema["paths"][path][method]
        assert {"AdminKeyAuth": []} in operation["security"]
        assert operation["responses"]["200"]["content"]["text/plain; charset=windows-1251"][
            "schema"
        ] == {"type": "string", "format": "binary"}


def test_post_finance_reuses_existing_rules() -> None:
    body = BankStatementRequest(inn=INN, avg_monthly_revenue_rub=700000, seed=123)
    assert body.finance().vat_rate_percent == 0
    spec = next(s for s in builtin_scenarios(TODAY) if s.code == "garipov")
    finance = resolved_spec(spec).finance
    assert finance is not None
    assert finance.noise_percent == 0
