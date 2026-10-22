"""Автозаполнение для клиента: источник и время у каждого поля (T-220, 50-07)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.modules.integrations import System


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ProfileField(Camel):
    value: str | int | bool | None = None
    source: System
    retrieved_at: datetime | None = None
    confirmed: bool = False


class RelatedCompany(Camel):
    id: UUID
    inn: str
    name: str


type CompanyForm = Literal["LEGAL", "IP", "SELF_EMPLOYED"]
type Eligibility = Literal[
    "ELIGIBLE", "UNCONFIRMED", "NOT_ELIGIBLE", "COMPANY_NOT_ACTIVE", "PERSON_ROLES"
]


class CompanyProfile(Camel):
    company_id: UUID | None
    inn: str
    form: CompanyForm | None
    eligibility: Eligibility
    fields: dict[str, ProfileField]
    related_companies: list[RelatedCompany]
    fetched_at: datetime
