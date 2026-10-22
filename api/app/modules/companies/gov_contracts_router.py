"""Чтение госконтрактов для шага заявки (T-224)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.modules import auth
from app.modules.companies import gov_contracts

router = APIRouter(prefix="/companies", tags=["компании"])


@router.get(
    "/{company_id}/gov-contracts",
    operation_id="listCompanyGovContracts",
    response_model=gov_contracts.GovContractPage,
)
def list_contracts(
    company_id: UUID,
    principal: auth.ClientPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(pattern=r"^\d{19}$")] = None,
    status: gov_contracts.ContractStatus | None = None,
) -> gov_contracts.GovContractPage:
    return gov_contracts.list_for(principal, company_id, limit, cursor, status)
