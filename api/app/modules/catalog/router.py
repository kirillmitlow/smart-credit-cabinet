"""Ручки каталога, калькулятора и мастера (50-07). Роутер тонкий: разобрать → сервис → ответ."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.modules import auth
from app.shared import clock, db

from . import calculator, service, wizard
from .facts import CompanyFacts, facts_for
from .policy import get_policy
from .schemas import (
    PaymentOut,
    PaymentRequest,
    ProductList,
    ProductOut,
    WizardAnswers,
    WizardRequest,
    WizardResult,
)

router = APIRouter(tags=["каталог"])

# Слушатель результата мастера: `applications` кладёт ответы в черновик (catalog ниже по графу
# модулей и сам заявки не знает, 50-04). Возвращает id черновика.
RecommendationListener = Callable[
    [Session, auth.Principal, UUID | None, WizardAnswers, WizardResult], UUID | None
]
_listeners: list[RecommendationListener] = []


def register_recommendation_listener(listener: RecommendationListener) -> None:
    _listeners.append(listener)


def _facts(session: Session, principal: auth.Principal) -> CompanyFacts:
    company_id = principal.active_company_id
    if company_id is None or not principal.can_access(company_id):
        return CompanyFacts()
    return facts_for(session, company_id)


def _products(principal: auth.Principal) -> ProductList:
    policy = get_policy()
    with db.transaction() as session:
        facts = _facts(session, principal)
    return ProductList(items=service.list_products(policy, facts, clock.today()))


@router.get(
    "/products",
    operation_id="listProducts",
    summary="Каталог: шесть продуктов и доступность каждого компании",
    response_model=ProductList,
    response_model_by_alias=True,
)
async def list_products(principal: auth.ClientPrincipal) -> ProductList:
    return await run_in_threadpool(_products, principal)


def _product(principal: auth.Principal, code: str) -> ProductOut:
    policy = get_policy()
    with db.transaction() as session:
        facts = _facts(session, principal)
    return service.get_product(policy, code, facts, clock.today())


@router.get(
    "/products/{code}",
    operation_id="getProduct",
    summary="Продукт: границы, документы, доступность",
    response_model=ProductOut,
    response_model_by_alias=True,
)
async def get_product(
    code: Annotated[str, Path(pattern=r"^[A-Z_]{3,32}$")], principal: auth.ClientPrincipal
) -> ProductOut:
    return await run_in_threadpool(_product, principal, code)


def _calculate(body: PaymentRequest) -> PaymentOut:
    return calculator.calculate(
        get_policy(), body.product_code, body.amount_rub, body.term_months, body.rate_percent
    )


@router.post(
    "/calculator/payment",
    operation_id="calculatePayment",
    summary="Платёж, переплата и ставка «от» для суммы, срока и продукта",
    response_model=PaymentOut,
    response_model_by_alias=True,
)
async def calculate_payment(body: PaymentRequest, _principal: auth.ClientPrincipal) -> PaymentOut:
    return await run_in_threadpool(_calculate, body)


def _recommend(principal: auth.Principal, body: WizardRequest) -> WizardResult:
    policy = get_policy()
    with db.transaction() as session:
        facts = _facts(session, principal)
        result = wizard.recommend(policy, body.answers, facts, clock.today())
        for listener in _listeners:
            application_id = listener(session, principal, body.application_id, body.answers, result)
            if application_id is not None:
                result = result.model_copy(update={"application_id": application_id})
        return result


@router.post(
    "/wizard/recommendations",
    operation_id="recommendProduct",
    summary="Мастер подбора: ответы → основной продукт и одна альтернатива",
    response_model=WizardResult,
    response_model_by_alias=True,
)
async def recommend(body: WizardRequest, principal: auth.ClientPrincipal) -> WizardResult:
    return await run_in_threadpool(_recommend, principal, body)
