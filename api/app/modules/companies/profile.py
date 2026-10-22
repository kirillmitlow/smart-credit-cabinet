"""Карточка компании из реестра, ФНС и АБС (T-220). Сеть всегда вне транзакции БД.

Профиль нужен для автозаполнения. Решение не доверяет ни этому кэшу, ни ручным дополнениям:
конвейер запрашивает источники заново. Недоступность помечает поля неподтверждёнными.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules import auth
from app.modules.companies import service
from app.modules.companies.models import Company
from app.modules.companies.profile_schemas import (
    CompanyForm,
    CompanyProfile,
    Eligibility,
    ProfileField,
    RelatedCompany,
)
from app.modules.integrations import (
    CompanyRecord,
    Customer,
    Ok,
    Result,
    SmeStatus,
    System,
    TaxProfile,
    get_integrations,
)
from app.shared import clock, db
from app.shared.errors import AppError, not_found
from app.shared.settings import get_settings

REGISTRY_FIELDS = (
    "name",
    "inn",
    "ogrn",
    "kpp",
    "registrationDate",
    "status",
    "okved",
    "address",
    "directorName",
    "directorInn",
)
TAX_FIELDS = ("taxRegime", "headcount", "taxDebtRub", "smeCategory")
BANK_FIELDS = ("isBankCustomer", "customerSince")


@dataclass(frozen=True)
class Target:
    id: UUID
    inn: str
    kind: str
    name: str
    cached: CompanyProfile | None = None


def _visible(principal: auth.Principal, company: Company | None) -> bool:
    member = principal.membership(company.id) if company else None
    return member is not None and member.role != "GUARANTOR"


def _target(session: Session, principal: auth.Principal, company: Company | None) -> Target:
    if company is None or not _visible(principal, company):
        raise not_found("Компания")
    cached = None
    if company.profile_fetched_at and company.profile and company.profile.get("autofill"):
        if clock.system_now() - company.profile_fetched_at < timedelta(
            hours=get_settings().cache_ttl_autofill_hours
        ):
            try:
                cached = CompanyProfile.model_validate(company.profile["autofill"])
            except ValidationError:
                pass  # старый формат кэша: запросить источники заново
    return Target(company.id, company.inn, company.kind, company.name, cached)


def _field[T](result: Result[T], value: str | int | bool | None) -> ProfileField:
    return ProfileField(
        value=value,
        source=result.snapshot_meta.system if isinstance(result, Ok) else result.system,
        retrieved_at=result.snapshot_meta.retrieved_at if isinstance(result, Ok) else None,
        confirmed=isinstance(result, Ok) and value is not None,
    )


def assemble(
    target: Target,
    registry: Result[CompanyRecord | None],
    tax: Result[TaxProfile | None],
    sme: Result[SmeStatus],
    bank: Result[Customer | None],
) -> CompanyProfile:
    fields = {
        **{key: ProfileField(source=System.REGISTRY) for key in REGISTRY_FIELDS},
        **{key: ProfileField(source=System.TAX) for key in TAX_FIELDS},
        **{key: ProfileField(source=System.BANK_CORE) for key in BANK_FIELDS},
    }
    record = registry.data if isinstance(registry, Ok) else None
    form = cast(CompanyForm, target.kind)
    eligibility: Eligibility = "UNCONFIRMED"
    if record is not None:
        values: dict[str, str | int | bool | None] = {
            "inn": record.inn,
            "name": record.name,
            "ogrn": record.ogrn,
            "kpp": record.kpp,
            "registrationDate": record.registration_date.isoformat(),
            "status": record.status_code,
            "okved": record.okved_main,
            "address": record.address,
            "directorName": record.director.full_name if record.director else None,
            "directorInn": record.director.inn if record.director else None,
        }
        fields.update({key: _field(registry, value) for key, value in values.items()})
        form = "IP" if record.kind == "INDIVIDUAL_ENTREPRENEUR" else "LEGAL"
        eligibility = "ELIGIBLE" if record.status_code == "ACTIVE" else "COMPANY_NOT_ACTIVE"
    else:
        fields["inn"].value = target.inn
        fields["name"].value = target.name
    profile = tax.data if isinstance(tax, Ok) else None
    if profile is not None:
        regime = next((x.code for x in profile.regimes if x.year == clock.today().year), None)
        fields.update(
            {
                "taxRegime": _field(tax, regime),
                "headcount": _field(tax, profile.avg_headcount),
                "taxDebtRub": _field(tax, profile.tax_debt_rub),
            }
        )
    if isinstance(sme, Ok):
        fields["smeCategory"] = _field(sme, sme.data.category if sme.data.in_registry else None)
    if isinstance(bank, Ok):
        fields["isBankCustomer"] = _field(bank, bank.data is not None)
        fields["customerSince"] = _field(
            bank, bank.data.customer_since.isoformat() if bank.data else None
        )
    return CompanyProfile(
        company_id=target.id,
        inn=target.inn,
        form=form,
        eligibility=eligibility,
        fields=fields,
        related_companies=[],
        fetched_at=clock.system_now(),
    )


def _personal(principal: auth.Principal, inn: str, target: Target | None) -> CompanyProfile:
    ports = get_integrations()
    with ThreadPoolExecutor(max_workers=2) as pool:
        roles_future = pool.submit(ports.registry.get_person_roles, inn)
        npd_future = pool.submit(ports.tax.get_self_employed_status, inn)
        roles, npd = roles_future.result(), npd_future.result()
    related: list[RelatedCompany] = []
    if isinstance(roles, Ok):
        with db.transaction() as session:
            seen: set[UUID] = set()
            for role in roles.data.roles:
                company = service.by_inn(session, role.entity_inn)
                if company and company.id not in seen and _visible(principal, company):
                    related.append(
                        RelatedCompany(id=company.id, inn=company.inn, name=company.name)
                    )
                    seen.add(company.id)
    self_employed = isinstance(npd, Ok) and npd.data.is_self_employed
    return CompanyProfile(
        company_id=target.id if target else None,
        inn=inn,
        form="SELF_EMPLOYED" if self_employed else None,
        eligibility="NOT_ELIGIBLE"
        if self_employed
        else "PERSON_ROLES"
        if related
        else "UNCONFIRMED",
        fields={
            "isSelfEmployed": _field(
                npd, npd.data.is_self_employed if isinstance(npd, Ok) else None
            )
        },
        related_companies=related,
        fetched_at=clock.system_now(),
    )


def _collect(principal: auth.Principal, target: Target) -> CompanyProfile:
    ports = get_integrations()
    with ThreadPoolExecutor(max_workers=4) as pool:
        reg = pool.submit(ports.registry.get_company, target.inn)
        tax = pool.submit(ports.tax.get_tax_profile, target.inn)
        sme = pool.submit(ports.tax.get_sme_status, target.inn)
        bank = pool.submit(ports.bank_core.get_customer, target.inn)
        results = reg.result(), tax.result(), sme.result(), bank.result()
    if isinstance(results[0], Ok) and results[0].data is None and len(target.inn) == 12:
        result = _personal(principal, target.inn, target)
    else:
        result = assemble(target, *results)
    with db.transaction() as session:
        row = session.get(Company, target.id, with_for_update=True)
        if row is None:
            raise not_found("Компания")
        row.profile = {
            **(row.profile or {}),
            "autofill": result.model_dump(mode="json", by_alias=True),
        }
        row.profile_fetched_at = result.fetched_at
        if result.fields.get("registrationDate") and result.fields["registrationDate"].confirmed:
            # Только подтверждённые факты из источника участвуют в подборе продуктов.
            row.registered_on = date.fromisoformat(str(result.fields["registrationDate"].value))
        customer = result.fields.get("isBankCustomer")
        if customer and customer.confirmed:
            row.is_bank_customer = bool(customer.value)
            row.profile = {**row.profile, "customerSince": result.fields["customerSince"].value}
    return result


def lookup(principal: auth.Principal, inn: str) -> CompanyProfile:
    if not service.inn_is_valid(inn):
        raise AppError(422, "INN_INVALID", "Неверная контрольная сумма ИНН")
    with db.transaction() as session:
        company = service.by_inn(session, inn)
        if company is not None:
            target = _target(session, principal, company)
        elif inn == principal.person_inn:
            target = None
        else:
            raise not_found("Компания")
    return _collect(principal, target) if target else _personal(principal, inn, None)


def get_profile(principal: auth.Principal, company_id: UUID) -> CompanyProfile:
    with db.transaction() as session:
        target = _target(session, principal, session.get(Company, company_id))
    return target.cached or _collect(principal, target)
