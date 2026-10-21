"""Порт `registry`: ЕГРЮЛ/ЕГРИП и реестр банкротств ЕФРСБ (моки 4.1–4.3, T-232).

DTO под JSON мока приватные, наружу уходят внутренние модели. Код мока не импортируем.
`404` на карточку компании — нормальный ответ (самозанятый), поэтому `Ok(None)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from pydantic import Field

from app.modules.integrations._dto import Dto
from app.modules.integrations.client import IntegrationClient
from app.modules.integrations.policy import REGISTRY
from app.modules.integrations.results import Result

# --- внутренние модели ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Unreliable:
    """Отметка ЕГРЮЛ «сведения недостоверны» (правило в `v1` выключено, данные забираем)."""

    since: date
    grn: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class PendingExclusion:
    decision_date: date
    grn: str | None
    objections_deadline: date | None


@dataclass(frozen=True, slots=True)
class Director:
    full_name: str
    inn: str | None
    position: str | None
    since: date | None
    unreliable: Unreliable | None


@dataclass(frozen=True, slots=True)
class Founder:
    kind: str  # PERSON | LEGAL_ENTITY
    full_name: str | None
    inn: str | None
    share_percent: float | None
    share_nominal_rub: int | None
    unreliable: Unreliable | None


@dataclass(frozen=True, slots=True)
class CompanyRecord:
    kind: str  # LEGAL_ENTITY | INDIVIDUAL_ENTREPRENEUR
    inn: str
    name: str
    ogrn: str | None
    kpp: str | None
    registration_date: date
    status_code: str  # ACTIVE | LIQUIDATING | LIQUIDATED | BANKRUPT | REORGANIZING | CEASED
    status_since: date | None
    okved_main: str | None
    okved_additional: tuple[str, ...]
    region_code: str | None
    address: str | None
    address_unreliable: Unreliable | None
    authorized_capital_rub: int | None
    director: Director | None
    founders: tuple[Founder, ...]
    pending_exclusion: PendingExclusion | None
    tax_authority_code: str | None


@dataclass(frozen=True, slots=True)
class PersonRole:
    role: str  # INDIVIDUAL_ENTREPRENEUR | DIRECTOR | FOUNDER
    entity_inn: str
    entity_name: str | None
    entity_status: str | None
    since: date | None
    share_percent: float | None


@dataclass(frozen=True, slots=True)
class PersonRoles:
    person_inn: str
    roles: tuple[PersonRole, ...]


@dataclass(frozen=True, slots=True)
class BankruptcyCase:
    """Дело о банкротстве. В отчёте БКИ те же поля, кроме `subject_type`."""

    case_number: str
    subject_type: str | None  # LEGAL_ENTITY | PERSON
    stage: str  # OBSERVATION | RESTRUCTURING | PROPERTY_REALIZATION | COMPLETED
    started_at: date
    completed_at: date | None

    @property
    def is_completed(self) -> bool:
        return self.stage == "COMPLETED"


# --- DTO под JSON мока ---------------------------------------------------------------------------


class _UnreliableDto(Dto):
    since: date
    grn: str | None = None
    reason: str | None = None


class _PendingExclusionDto(Dto):
    decision_date: date
    grn: str | None = None
    objections_deadline: date | None = None


class _CodeNameDto(Dto):
    code: str
    name: str | None = None


class _StatusDto(Dto):
    code: str
    since: date | None = None


class _AddressDto(Dto):
    region_code: str | None = None
    full: str | None = None
    unreliable: _UnreliableDto | None = None


class _DirectorDto(Dto):
    full_name: str
    inn: str | None = None
    position: str | None = None
    since: date | None = None
    unreliable: _UnreliableDto | None = None


class _FounderDto(Dto):
    type: str
    full_name: str | None = None
    inn: str | None = None
    share_percent: float | None = None
    share_nominal_rub: int | None = None
    unreliable: _UnreliableDto | None = None


class _PersonDto(Dto):
    full_name: str


class _TaxAuthorityDto(Dto):
    code: str


class _CompanyDto(Dto):
    """И организация, и ИП: различаются полем `type`, лишнего каждому типу нет."""

    type: str
    inn: str
    registration_date: date
    status: _StatusDto
    ogrn: str | None = None
    ogrnip: str | None = None
    kpp: str | None = None
    short_name: str | None = None
    full_name: str | None = None
    person: _PersonDto | None = None
    pending_exclusion: _PendingExclusionDto | None = None
    address: _AddressDto | None = None
    region: _CodeNameDto | None = None
    authorized_capital_rub: int | None = None
    director: _DirectorDto | None = None
    founders: list[_FounderDto] = Field(default_factory=list)
    okved_main: _CodeNameDto | None = None
    okved_additional: list[_CodeNameDto] = Field(default_factory=list)
    tax_authority: _TaxAuthorityDto | None = None


class _RoleDto(Dto):
    role: str
    entity_inn: str
    entity_name: str | None = None
    entity_status: str | None = None
    since: date | None = None
    share_percent: float | None = None


class _RolesDto(Dto):
    person_inn: str
    roles: list[_RoleDto]


class _CaseDto(Dto):
    case_number: str
    subject_type: str | None = None
    stage: str
    started_at: date
    completed_at: date | None = None


class _BankruptciesDto(Dto):
    bankruptcies: list[_CaseDto]


# --- маппинг -------------------------------------------------------------------------------------


def _unreliable(dto: _UnreliableDto | None) -> Unreliable | None:
    return Unreliable(dto.since, dto.grn, dto.reason) if dto else None


def map_company(payload: object) -> CompanyRecord:
    dto = _CompanyDto.model_validate(payload)
    if dto.type == "LEGAL_ENTITY":
        name = dto.short_name or dto.full_name
    elif dto.type == "INDIVIDUAL_ENTREPRENEUR":
        name = dto.person.full_name if dto.person else None
    else:
        raise ValueError(f"Неизвестный тип записи реестра: {dto.type}")
    if not name:
        raise ValueError("В карточке реестра нет названия")
    address = dto.address
    director = dto.director
    return CompanyRecord(
        kind=dto.type,
        inn=dto.inn,
        name=name,
        ogrn=dto.ogrn or dto.ogrnip,
        kpp=dto.kpp,
        registration_date=dto.registration_date,
        status_code=dto.status.code,
        status_since=dto.status.since,
        okved_main=dto.okved_main.code if dto.okved_main else None,
        okved_additional=tuple(item.code for item in dto.okved_additional),
        region_code=address.region_code if address else (dto.region.code if dto.region else None),
        address=address.full if address else None,
        address_unreliable=_unreliable(address.unreliable) if address else None,
        authorized_capital_rub=dto.authorized_capital_rub,
        director=Director(
            director.full_name,
            director.inn,
            director.position,
            director.since,
            _unreliable(director.unreliable),
        )
        if director
        else None,
        founders=tuple(
            Founder(
                f.type,
                f.full_name,
                f.inn,
                f.share_percent,
                f.share_nominal_rub,
                _unreliable(f.unreliable),
            )
            for f in dto.founders
        ),
        pending_exclusion=PendingExclusion(
            dto.pending_exclusion.decision_date,
            dto.pending_exclusion.grn,
            dto.pending_exclusion.objections_deadline,
        )
        if dto.pending_exclusion
        else None,
        tax_authority_code=dto.tax_authority.code if dto.tax_authority else None,
    )


def map_roles(payload: object) -> PersonRoles:
    dto = _RolesDto.model_validate(payload)
    return PersonRoles(
        person_inn=dto.person_inn,
        roles=tuple(
            PersonRole(
                r.role, r.entity_inn, r.entity_name, r.entity_status, r.since, r.share_percent
            )
            for r in dto.roles
        ),
    )


def map_bankruptcies(payload: object) -> tuple[BankruptcyCase, ...]:
    dto = _BankruptciesDto.model_validate(payload)
    return tuple(
        BankruptcyCase(c.case_number, c.subject_type, c.stage, c.started_at, c.completed_at)
        for c in dto.bankruptcies
    )


# --- порт ----------------------------------------------------------------------------------------


class RegistryAdapter:
    def __init__(self, client: IntegrationClient) -> None:
        self._client = client

    def get_company(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[CompanyRecord | None]:
        """Карточка ЕГРЮЛ/ЕГРИП. Нет в реестре (например, самозанятый) → `Ok(None)`."""
        return self._client.call(
            policy=REGISTRY,
            method="GET",
            path=f"/api/v1/companies/{inn}",
            parse=map_company,
            allow_404=True,
            subject_inn=inn,
            application_id=application_id,
            resource="registry:company",
        )

    def get_person_roles(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[PersonRoles]:
        """Где человек ИП, директор или учредитель. Ничего нет → `roles=()`, а не ошибка."""
        return self._client.call(
            policy=REGISTRY,
            method="GET",
            path=f"/api/v1/persons/{inn}/roles",
            parse=map_roles,
            subject_inn=inn,
            application_id=application_id,
            resource="registry:roles",
        )

    def get_bankruptcies(
        self, inn: str, *, application_id: UUID | None = None
    ) -> Result[tuple[BankruptcyCase, ...]]:
        """Дела ЕФРСБ по одному субъекту (компания, директор или учредитель-человек).

        Список субъектов собирает конвейер; нет дел → пустой кортеж.
        """
        return self._client.call(
            policy=REGISTRY,
            method="GET",
            path=f"/api/v1/bankruptcies/{inn}",
            parse=map_bankruptcies,
            subject_inn=inn,
            application_id=application_id,
            resource="registry:bankruptcies",
        )
