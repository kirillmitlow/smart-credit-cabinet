"""Схемы mock-registry (разделы 4.1–4.3, 8.3).

Тело админ-API (`RegistryBody`) собрано из тех же карточек, что и ответы бизнес-API, только без
`meta`. Карточки закрыты для лишних полей (`extra="forbid"`): КПП у ИП или учредители у ИП
дают `422` при записи, а не молча теряются.
"""

from __future__ import annotations

import datetime as dt
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, StringConstraints, model_validator

from app.common.inn import inn_is_valid, ogrn_is_valid
from app.common.schemas import CamelModel, Meta


def _check_inn(value: str) -> str:
    if not inn_is_valid(value):
        raise ValueError("ИНН должен состоять из 10 или 12 цифр с верной контрольной суммой")
    return value


def _check_person_inn(value: str) -> str:
    _check_inn(value)
    if len(value) != 12:
        raise ValueError("ИНН человека — 12 цифр")
    return value


def _check_company_inn(value: str) -> str:
    _check_inn(value)
    if len(value) != 10:
        raise ValueError("ИНН организации — 10 цифр")
    return value


Inn = Annotated[str, AfterValidator(_check_inn)]
PersonInn = Annotated[str, AfterValidator(_check_person_inn)]
CompanyInn = Annotated[str, AfterValidator(_check_company_inn)]
Grn13 = Annotated[str, StringConstraints(pattern=r"^\d{13}$")]
Grn15 = Annotated[str, StringConstraints(pattern=r"^\d{15}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=500)]
RegionCode = Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
OkvedCode = Annotated[str, StringConstraints(pattern=r"^\d{2}(\.\d{1,2}){0,2}$")]

LegalEntityStatusCode = Literal["ACTIVE", "LIQUIDATING", "LIQUIDATED", "BANKRUPT", "REORGANIZING"]
IpStatusCode = Literal["ACTIVE", "CEASED", "BANKRUPT"]
RoleCode = Literal["INDIVIDUAL_ENTREPRENEUR", "DIRECTOR", "FOUNDER"]
BankruptcyStage = Literal["OBSERVATION", "RESTRUCTURING", "PROPERTY_REALIZATION", "COMPLETED"]
SubjectType = Literal["LEGAL_ENTITY", "PERSON"]


class Strict(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Unreliable(Strict):
    """Отметка недостоверности (адрес, директор, учредитель)."""

    since: date
    grn: Grn13
    reason: Text


class PendingExclusion(Strict):
    decision_date: date
    grn: Grn13
    objections_deadline: date


class LegalForm(Strict):
    okopf: Annotated[str, StringConstraints(pattern=r"^\d{5}$")]
    name: Text


class LegalEntityStatus(Strict):
    code: LegalEntityStatusCode
    name: Text
    since: date


class IpStatus(Strict):
    code: IpStatusCode
    name: Text
    since: date


class Address(Strict):
    region_code: RegionCode
    region_name: Text
    full: Text
    unreliable: Unreliable | None = None


class Director(Strict):
    full_name: Text
    inn: PersonInn
    position: Text
    since: date
    unreliable: Unreliable | None = None


class Founder(Strict):
    type: Literal["PERSON", "LEGAL_ENTITY"]
    full_name: Text
    inn: Inn
    share_percent: Annotated[float, Field(gt=0, le=100)]
    share_nominal_rub: Annotated[int, Field(ge=0)]
    unreliable: Unreliable | None = None

    @model_validator(mode="after")
    def _inn_matches_type(self) -> Founder:
        expected = 12 if self.type == "PERSON" else 10
        if len(self.inn) != expected:
            raise ValueError(
                f"У учредителя типа {self.type} ИНН из {expected} цифр, получено {len(self.inn)}"
            )
        return self


class Okved(Strict):
    code: OkvedCode
    name: Text


class TaxAuthority(Strict):
    code: Annotated[str, StringConstraints(pattern=r"^\d{4}$")]
    name: Text


class LastRecordLe(Strict):
    grn: Grn13
    date: dt.date


class LastRecordIp(Strict):
    grn: Grn15
    date: dt.date


class IpPerson(Strict):
    last_name: Text
    first_name: Text
    middle_name: Text | None = None
    full_name: Text


class IpRegion(Strict):
    code: RegionCode
    name: Text


class LegalEntityCard(Strict):
    """Организация (ЕГРЮЛ) — формат ответа `GET /companies/{inn}` без `meta`."""

    type: Literal["LEGAL_ENTITY"]
    inn: CompanyInn
    kpp: Annotated[str, StringConstraints(pattern=r"^\d{4}[\dA-Z]{2}\d{3}$")]
    ogrn: Annotated[str, StringConstraints(pattern=r"^\d{13}$")]
    registration_date: date
    full_name: Text
    short_name: Text
    legal_form: LegalForm
    status: LegalEntityStatus
    pending_exclusion: PendingExclusion | None = None
    address: Address
    authorized_capital_rub: Annotated[int, Field(ge=0)]
    director: Director | None = None
    founders: list[Founder] = []
    okved_main: Okved
    okved_additional: list[Okved] = []
    tax_authority: TaxAuthority
    last_record: LastRecordLe

    @model_validator(mode="after")
    def _consistent(self) -> LegalEntityCard:
        if not ogrn_is_valid(self.ogrn):
            raise ValueError("ОГРН не проходит проверку контрольной цифры")
        if self.kpp[:4] != self.inn[:4]:
            raise ValueError("КПП начинается с тех же 4 цифр, что и ИНН")
        if self.tax_authority.code != self.inn[:4]:
            raise ValueError("Код налоговой (taxAuthority.code) — первые 4 цифры ИНН")
        if self.legal_form.okopf.startswith("122") and self.founders:
            raise ValueError("У акционерного общества список учредителей пуст (раздел 4.1)")
        if self.legal_form.okopf == "12300" and not self.founders:
            raise ValueError("У ООО учредителей минимум один (раздел 4.1)")
        if sum(f.share_percent for f in self.founders) > 100.0001:
            raise ValueError("Сумма долей учредителей больше 100%")
        if len({f.inn for f in self.founders}) != len(self.founders):
            raise ValueError("Учредитель указан дважды")
        return self


class IndividualEntrepreneurCard(Strict):
    """ИП (ЕГРИП): без КПП, руководителя, учредителей, капитала и полного адреса."""

    type: Literal["INDIVIDUAL_ENTREPRENEUR"]
    inn: PersonInn
    ogrnip: Annotated[str, StringConstraints(pattern=r"^\d{15}$")]
    registration_date: date
    person: IpPerson
    status: IpStatus
    region: IpRegion
    okved_main: Okved
    okved_additional: list[Okved] = []
    tax_authority: TaxAuthority
    last_record: LastRecordIp

    @model_validator(mode="after")
    def _consistent(self) -> IndividualEntrepreneurCard:
        if not ogrn_is_valid(self.ogrnip):
            raise ValueError("ОГРНИП не проходит проверку контрольной цифры")
        if self.tax_authority.code != self.inn[:4]:
            raise ValueError("Код налоговой (taxAuthority.code) — первые 4 цифры ИНН")
        return self


EntityCard = Annotated[LegalEntityCard | IndividualEntrepreneurCard, Field(discriminator="type")]


class LegalEntityResponse(LegalEntityCard):
    meta: Meta


class IndividualEntrepreneurResponse(IndividualEntrepreneurCard):
    meta: Meta


CompanyResponse = Annotated[
    LegalEntityResponse | IndividualEntrepreneurResponse, Field(discriminator="type")
]


class PersonRecord(Strict):
    inn: PersonInn
    last_name: Text
    first_name: Text
    middle_name: Text | None = None
    birth_date: date | None = None


class BankruptcyCase(Strict):
    case_number: Annotated[str, StringConstraints(min_length=3, max_length=64)]
    subject_type: SubjectType
    stage: BankruptcyStage
    started_at: date
    completed_at: date | None = None

    @model_validator(mode="after")
    def _dates_match_stage(self) -> BankruptcyCase:
        if self.stage == "COMPLETED" and self.completed_at is None:
            raise ValueError("У завершённого дела (COMPLETED) нужна дата завершения completedAt")
        if self.stage != "COMPLETED" and self.completed_at is not None:
            raise ValueError("Дата завершения completedAt бывает только при stage = COMPLETED")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Дело не может завершиться раньше начала")
        return self


class BankruptcyRecord(BankruptcyCase):
    """Дело в теле админ-API: с ИНН субъекта (компании или человека из этого же тела)."""

    subject_inn: Inn


class RegistryBody(Strict):
    """Тело `PUT /admin/subjects/{inn}` (8.3)."""

    entity: EntityCard | None = None
    persons: list[PersonRecord] = []
    bankruptcies: list[BankruptcyRecord] = []


class PersonRole(CamelModel):
    role: RoleCode
    entity_inn: str
    entity_name: str
    entity_status: str
    since: date
    share_percent: float | None


class PersonRolesResponse(CamelModel):
    meta: Meta
    person_inn: str
    roles: list[PersonRole]


class BankruptciesResponse(CamelModel):
    meta: Meta
    inn: str
    bankruptcies: list[BankruptcyCase]
