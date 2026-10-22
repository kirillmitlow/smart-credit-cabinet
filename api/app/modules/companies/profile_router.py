"""Ручки автозаполнения компании (T-220). Чужие компании проверяются до вызова источников."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from app.modules import auth
from app.modules.companies import profile
from app.modules.companies.profile_limit import check_limit
from app.modules.companies.profile_schemas import CompanyProfile

router = APIRouter(prefix="/companies", tags=["компании"])


@router.get("/lookup/{inn}", operation_id="lookupCompany", response_model=CompanyProfile)
def lookup_company(
    inn: Annotated[str, Path(pattern=r"^\d{10}$|^\d{12}$")], principal: auth.ClientPrincipal
) -> CompanyProfile:
    check_limit(principal)
    return profile.lookup(principal, inn)


@router.get("/{company_id}", operation_id="getCompanyProfile", response_model=CompanyProfile)
def company_profile(company_id: UUID, principal: auth.ClientPrincipal) -> CompanyProfile:
    check_limit(principal)
    return profile.get_profile(principal, company_id)
