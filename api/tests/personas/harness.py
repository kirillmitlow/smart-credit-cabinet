"""Обвязка тестов «персона проходит путь по API на живом стенде» (T-517, 70-05).

Стенд задают переменные окружения: `STAND_API_URL` (например http://127.0.0.1:8100) и
`STAND_SCENARIOS_URL` (http://127.0.0.1:8105). Без `STAND_API_URL` тесты персон пропускаются:
в CI их запускает отдельное задание с поднятым compose (T-512).

Ожидаемые исходы берутся из мока сценариев (`GET /api/v1/scenarios/{code}`), а не копируются в код.
Ожидание статуса — опрос с таймаутом по монотонным часам, без фиксированных пауз.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

API_ENV = "STAND_API_URL"
SCENARIOS_ENV = "STAND_SCENARIOS_URL"
ADMIN_KEY_ENV = "MOCK_ADMIN_KEY"
DEFAULT_ADMIN_KEY = "dev-admin-key"  # значение для разработки из .env.example
POLL_SECONDS = 0.5


def stand_url() -> str:
    url = os.environ.get(API_ENV)
    if not url:
        pytest.skip(f"{API_ENV} не задан: тесты персон идут только на поднятом стенде")
    return url.rstrip("/")


@dataclass(frozen=True)
class Expected:
    code: str
    outcome: str | None
    final_outcome: str | None
    reason_codes: list[str]
    inn: str
    # У orlov заявки нет: продукта и срока в сценарии не задано (он хочет только 300 тыс.)
    product_code: str | None
    amount_rub: int
    term_months: int | None


def scenario(code: str) -> dict[str, Any]:
    """Сценарий персоны из мока целиком: заявка, ожидания, учётки, развёрнутые данные."""
    url = os.environ.get(SCENARIOS_ENV, "http://127.0.0.1:8105").rstrip("/")
    key = os.environ.get(ADMIN_KEY_ENV, DEFAULT_ADMIN_KEY)
    response = httpx.get(f"{url}/api/v1/scenarios/{code}", headers={"X-Admin-Key": key}, timeout=10)
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def expected(code: str) -> Expected:
    """Ожидания сценария из мока: исход, коды причин, ИНН входа и условия заявки."""
    body = scenario(code)
    application = body["application"]
    term = application.get("termMonths")
    return Expected(
        code=code,
        outcome=body.get("expectedOutcome"),
        final_outcome=body.get("expectedFinalOutcome"),
        reason_codes=list(body.get("expectedReasonCodes") or []),
        inn=str(body["inn"]),
        product_code=application.get("productCode"),
        amount_rub=int(application["amountRub"]),
        term_months=int(term) if term is not None else None,
    )


def check(response: httpx.Response, status: int = 200) -> Any:
    """Ответ с ожидаемым статусом или понятное падение с телом проблемы."""
    if response.status_code != status:
        raise AssertionError(
            f"{response.request.method} {response.request.url.path}: ждали {status}, "
            f"пришло {response.status_code}: {response.text[:500]}"
        )
    return response.json() if response.content else None


def login(client: httpx.Client, inn: str, role: str | None = None) -> dict[str, Any]:
    """Вход клиента по ИНН и коду из демо-режима (D-062); выбирает компанию с этим ИНН.

    `role` выбирает пользователя с этой ролью (у СтанкоПрома двое: бухгалтер и директор);
    если такой роли нет, входит первый.
    """
    roles = check(client.get(f"/auth/roles/{inn}"))
    people = roles.get("people") or []
    if not people:
        raise AssertionError(f"По ИНН {inn} некому войти: {roles}")
    company = roles.get("company") or {}
    person = next((p for p in people if role and p.get("role") == role), people[0])
    issued = check(
        client.post(
            "/auth/request-code",
            json={"userId": person["userId"], "companyId": company.get("id")},
        )
    )
    if not issued.get("demoCode"):
        raise AssertionError("Стенд не в демо-режиме: код на экран не выдан")
    me = check(
        client.post(
            "/auth/verify-code", json={"requestId": issued["requestId"], "code": issued["demoCode"]}
        )
    )
    if company.get("id") and me["activeCompanyId"] != company["id"]:
        me = check(client.put("/me/active-company", json={"companyId": company["id"]}))
    return me


TERMINAL = frozenset({"DISBURSED", "REJECTED", "WITHDRAWN", "EXPIRED"})


def require_clean_persona(client: httpx.Client, code: str) -> None:
    """Пропуск, если персона уже прошла путь: её кредит или заявка в работе меняют решение.

    Пример: второй кредит Соколовой честно даёт `COUNTER_OFFER`, потому что платёж по первому
    входит в долговую нагрузку. Повтор на том же стенде требует сброса персоны (T-129).
    """
    loans = check(client.get("/loans"))["items"]
    busy = [
        a["number"]
        for a in check(client.get("/applications"))["items"]
        if a["status"] not in TERMINAL and a["status"] != "DRAFT"
    ]
    if loans or busy:
        pytest.skip(
            f"Персона {code} уже прошла путь (кредитов {len(loans)}, заявки в работе {busy}): "
            "нужен сброс стенда или персоны (T-129)"
        )


def wait_status(
    client: httpx.Client, application_id: str, wanted: set[str], timeout: float = 90.0
) -> dict[str, Any]:
    """Опрос заявки до одного из статусов; при таймауте — последний статус и журнал."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while True:
        application = check(client.get(f"/applications/{application_id}"))
        status = application["status"]
        if not seen or seen[-1] != status:
            seen.append(status)
        if status in wanted:
            return application
        if time.monotonic() > deadline:
            raise AssertionError(
                f"Заявка {application_id} не дошла до {sorted(wanted)} за {timeout:.0f} с. "
                f"Последний статус {status}; путь {' → '.join(seen)}"
            )
        time.sleep(POLL_SECONDS)


def sign_all_consents(client: httpx.Client, application_id: str) -> dict[str, Any]:
    """Подписать одним кодом все согласия, которые этот пользователь может подписать."""
    consents = check(client.get(f"/applications/{application_id}/consents"))
    items = [
        {"kind": item["kind"], "subjectInn": item["subjectInn"]}
        for item in consents["items"]
        if item["canSign"] and item["status"] != "SIGNED"
    ]
    if not items:
        return consents
    challenge = check(
        client.post(
            f"/applications/{application_id}/consents",
            json={"items": items, "acceptPepRules": True},
        )
    )
    check(
        client.post(
            f"/applications/{application_id}/consents/sign",
            json={
                "requestId": challenge["requestId"],
                "code": challenge["demoCode"],
                "items": challenge["items"],
            },
        )
    )
    return check(client.get(f"/applications/{application_id}/consents"))
