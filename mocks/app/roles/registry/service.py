"""Чтение и запись данных mock-registry: сборка карточек из таблиц и обратно (раздел 4.4).

«Субъект» админ-API — организация или ИП (по ИНН карточки) либо человек, записанный отдельно
(`entity: null`). Люди из `persons[]` запоминают, чьим PUT они записаны (`owner_inn`): так
`GET /admin/subjects/{inn}` возвращает тело в том же виде, в каком оно было записано.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.db import Origin
from app.common.problems import ProblemException
from app.roles.registry import models as m
from app.roles.registry import schemas as sc

LEGAL_ENTITY: Final = "LEGAL_ENTITY"
IP: Final = "INDIVIDUAL_ENTREPRENEUR"
DIRECTOR = "DIRECTOR"
FOUNDER = "FOUNDER"
ROLE_ORDER = {IP: 0, DIRECTOR: 1, FOUNDER: 2}

Card = sc.LegalEntityCard | sc.IndividualEntrepreneurCard


def person_full_name(last: str, first: str, middle: str | None) -> str:
    return " ".join(part for part in (last, first, middle) if part)


def data_actual_at(today: date) -> date:
    """Реестры отдают сведения «на вчера» (пример в 4.1: запрос 20.10, сведения на 19.10)."""
    return today - timedelta(days=1)


def _dump(model: sc.Strict | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump(mode="json", by_alias=True)


def _load[ModelT: sc.Strict](model: type[ModelT], data: dict[str, Any] | None) -> ModelT | None:
    return None if data is None else model.model_validate(data)


# --- чтение карточек ------------------------------------------------------------------------


async def _okved_names(session: AsyncSession, codes: Iterable[str]) -> dict[str, str]:
    rows = await session.execute(
        sa.select(m.Okved.code, m.Okved.name).where(m.Okved.code.in_(set(codes)))
    )
    return dict(rows.all())


async def _persons(session: AsyncSession, inns: Iterable[str]) -> dict[str, m.Person]:
    rows = await session.scalars(sa.select(m.Person).where(m.Person.inn.in_(set(inns))))
    return {p.inn: p for p in rows}


async def load_card(session: AsyncSession, inn: str) -> Card | None:
    entity = await session.get(m.Entity, inn)
    if entity is None:
        return None
    names = await _okved_names(session, [entity.okved_main, *entity.okved_additional])

    def okved(code: str) -> sc.Okved:
        return sc.Okved(code=code, name=names.get(code, code))

    common: dict[str, Any] = {
        "inn": entity.inn,
        "registration_date": entity.registration_date,
        "okved_main": okved(entity.okved_main),
        "okved_additional": [okved(c) for c in entity.okved_additional],
        "tax_authority": sc.TaxAuthority(
            code=entity.tax_authority_code, name=entity.tax_authority_name
        ),
    }
    if entity.type == IP:
        person = (await _persons(session, [entity.inn]))[entity.inn]
        return sc.IndividualEntrepreneurCard(
            type=IP,
            ogrnip=entity.ogrn,
            person=sc.IpPerson(
                last_name=person.last_name,
                first_name=person.first_name,
                middle_name=person.middle_name,
                full_name=person_full_name(person.last_name, person.first_name, person.middle_name),
            ),
            status=sc.IpStatus(
                code=entity.status_code,
                name=entity.status_name,
                since=entity.status_since,
            ),
            region=sc.IpRegion(code=entity.region_code, name=entity.region_name),
            last_record=sc.LastRecordIp(grn=entity.last_record_grn, date=entity.last_record_date),
            **common,
        )

    roles = (
        await session.scalars(
            sa.select(m.EntityRole)
            .where(m.EntityRole.entity_inn == inn)
            .order_by(m.EntityRole.position_order, m.EntityRole.id)
        )
    ).all()
    people = await _persons(session, [r.person_inn for r in roles if r.person_inn])

    def role_name(role: m.EntityRole) -> str:
        if role.person_inn:
            p = people[role.person_inn]
            return person_full_name(p.last_name, p.first_name, p.middle_name)
        return role.founder_name or ""

    director = None
    director_row = next((r for r in roles if r.role == DIRECTOR), None)
    if director_row is not None and director_row.person_inn:
        director = sc.Director(
            full_name=role_name(director_row),
            inn=director_row.person_inn,
            position=director_row.position or "",
            since=director_row.since,
            unreliable=_load(sc.Unreliable, director_row.unreliable),
        )
    founders = [
        sc.Founder(
            type="PERSON" if r.person_inn else "LEGAL_ENTITY",
            full_name=role_name(r),
            inn=r.person_inn or r.founder_entity_inn or "",
            share_percent=r.share_percent or 0,
            share_nominal_rub=r.share_nominal_rub or 0,
            unreliable=_load(sc.Unreliable, r.unreliable),
        )
        for r in roles
        if r.role == FOUNDER
    ]
    return sc.LegalEntityCard(
        type=LEGAL_ENTITY,
        kpp=entity.kpp or "",
        ogrn=entity.ogrn,
        full_name=entity.full_name or "",
        short_name=entity.short_name or "",
        legal_form=sc.LegalForm(okopf=entity.okopf_code or "", name=entity.okopf_name or ""),
        status=sc.LegalEntityStatus(
            code=entity.status_code,
            name=entity.status_name,
            since=entity.status_since,
        ),
        pending_exclusion=_load(sc.PendingExclusion, entity.pending_exclusion),
        address=sc.Address(
            region_code=entity.region_code,
            region_name=entity.region_name,
            full=entity.address_full or "",
            unreliable=_load(sc.Unreliable, entity.address_unreliable),
        ),
        authorized_capital_rub=entity.authorized_capital_rub or 0,
        director=director,
        founders=founders,
        last_record=sc.LastRecordLe(grn=entity.last_record_grn, date=entity.last_record_date),
        **common,
    )


async def person_roles(session: AsyncSession, inn: str) -> list[sc.PersonRole]:
    roles: list[sc.PersonRole] = []
    person = await session.get(m.Person, inn)
    individual = await session.get(m.Entity, inn)
    if person is not None and individual is not None and individual.type == IP:
        name = person_full_name(person.last_name, person.first_name, person.middle_name)
        roles.append(
            sc.PersonRole(
                role=IP,
                entity_inn=individual.inn,
                entity_name=f"ИП {name}",
                entity_status=individual.status_code,
                since=individual.registration_date,
                share_percent=None,
            )
        )
    rows = await session.execute(
        sa.select(m.EntityRole, m.Entity)
        .join(m.Entity, m.Entity.inn == m.EntityRole.entity_inn)
        .where(m.EntityRole.person_inn == inn)
    )
    for role, entity in rows:
        roles.append(
            sc.PersonRole(
                role=role.role,
                entity_inn=entity.inn,
                entity_name=entity.short_name or entity.full_name or "",
                entity_status=entity.status_code,
                since=role.since,
                share_percent=role.share_percent if role.role == FOUNDER else None,
            )
        )
    roles.sort(key=lambda r: (ROLE_ORDER[r.role], r.entity_inn))
    return roles


def _case(b: m.Bankruptcy) -> sc.BankruptcyCase:
    return sc.BankruptcyCase(
        case_number=b.case_number,
        subject_type=b.subject_type,
        stage=b.stage,
        started_at=b.started_at,
        completed_at=b.completed_at,
    )


async def bankruptcies_of(session: AsyncSession, inn: str) -> list[sc.BankruptcyCase]:
    """Дела субъекта от нового к старому; завершённые не пропадают."""
    rows = await session.scalars(
        sa.select(m.Bankruptcy)
        .where(m.Bankruptcy.subject_inn == inn)
        .order_by(m.Bankruptcy.started_at.desc(), m.Bankruptcy.case_number)
    )
    return [_case(b) for b in rows]


# --- тело админ-API: чтение -----------------------------------------------------------------


async def _subject(session: AsyncSession, inn: str) -> m.Entity | m.Person | None:
    entity = await session.get(m.Entity, inn)
    if entity is not None:
        return entity
    person = await session.get(m.Person, inn)
    return person if person is not None and person.owner_inn == inn else None


async def load_body(session: AsyncSession, inn: str) -> sc.RegistryBody | None:
    if await _subject(session, inn) is None:
        return None
    owned = (
        await session.scalars(
            sa.select(m.Person).where(m.Person.owner_inn == inn).order_by(m.Person.inn)
        )
    ).all()
    cases = (
        await session.scalars(
            sa.select(m.Bankruptcy)
            .where(m.Bankruptcy.subject_inn.in_([inn, *(p.inn for p in owned)]))
            .order_by(m.Bankruptcy.id)
        )
    ).all()
    return sc.RegistryBody(
        entity=await load_card(session, inn),
        persons=[
            sc.PersonRecord(
                inn=p.inn,
                last_name=p.last_name,
                first_name=p.first_name,
                middle_name=p.middle_name,
                birth_date=p.birth_date,
            )
            for p in owned
        ],
        bankruptcies=[
            sc.BankruptcyRecord(subject_inn=b.subject_inn, **_case(b).model_dump()) for b in cases
        ],
    )


async def subject_origin(session: AsyncSession, inn: str) -> tuple[str | None, str] | None:
    subject = await _subject(session, inn)
    return None if subject is None else (subject.scenario_code, subject.origin)


# --- тело админ-API: запись -----------------------------------------------------------------


async def clear_subject(session: AsyncSession, inn: str) -> None:
    """Убрать данные субъекта. Человек, нужный другой карточке, остаётся и переходит к ней."""
    owned = list(await session.scalars(sa.select(m.Person.inn).where(m.Person.owner_inn == inn)))
    await session.execute(
        sa.delete(m.Bankruptcy).where(m.Bankruptcy.subject_inn.in_([inn, *owned]))
    )
    await session.execute(sa.delete(m.EntityRole).where(m.EntityRole.entity_inn == inn))
    await session.execute(sa.delete(m.Entity).where(m.Entity.inn == inn))
    if not owned:
        return
    holders: dict[str, str] = {}
    by_role = await session.execute(
        sa.select(m.EntityRole.person_inn, m.EntityRole.entity_inn).where(
            m.EntityRole.person_inn.in_(owned)
        )
    )
    by_ip = await session.execute(
        sa.select(m.Entity.inn, m.Entity.inn).where(m.Entity.inn.in_(owned), m.Entity.type == IP)
    )
    for person_inn, entity_inn in [*by_role, *by_ip]:
        holders.setdefault(person_inn, entity_inn)
    for person_inn, entity_inn in holders.items():
        await session.execute(
            sa.update(m.Person).where(m.Person.inn == person_inn).values(owner_inn=entity_inn)
        )
    free = [p for p in owned if p not in holders]
    if free:
        await session.execute(sa.delete(m.Person).where(m.Person.inn.in_(free)))


async def replace_subject(
    session: AsyncSession, inn: str, body: sc.RegistryBody, scenario_code: str | None
) -> None:
    entity = body.entity
    if entity is not None:
        ogrn = entity.ogrn if isinstance(entity, sc.LegalEntityCard) else entity.ogrnip
        taken = await session.scalar(
            sa.select(m.Entity.inn).where(m.Entity.ogrn == ogrn, m.Entity.inn != inn)
        )
        if taken is not None:
            raise ProblemException(
                422, "VALIDATION_ERROR", f"ОГРН {ogrn} уже записан у другой карточки ({taken})"
            )
    await clear_subject(session, inn)
    origin = Origin.SCENARIO.value if scenario_code else Origin.RUNTIME.value
    mixin: dict[str, Any] = {"origin": origin, "scenario_code": scenario_code}

    if entity is not None:
        await _upsert_okved(session, entity)
    for person in body.persons:
        values = {
            "inn": person.inn,
            "owner_inn": inn,
            "last_name": person.last_name,
            "first_name": person.first_name,
            "middle_name": person.middle_name,
            "birth_date": person.birth_date,
            **mixin,
        }
        stmt = pg_insert(m.Person).values(values)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[m.Person.inn], set_={k: v for k, v in values.items() if k != "inn"}
            )
        )
    if entity is not None:
        await _insert_entity(session, entity, mixin)

    subjects = {inn, *(p.inn for p in body.persons)}
    await session.execute(sa.delete(m.Bankruptcy).where(m.Bankruptcy.subject_inn.in_(subjects)))
    session.add_all(
        m.Bankruptcy(
            subject_inn=b.subject_inn,
            subject_type=b.subject_type,
            case_number=b.case_number,
            stage=b.stage,
            started_at=b.started_at,
            completed_at=b.completed_at,
            **mixin,
        )
        for b in body.bankruptcies
    )
    await session.flush()


async def _upsert_okved(session: AsyncSession, entity: Card) -> None:
    for item in [entity.okved_main, *entity.okved_additional]:
        stmt = pg_insert(m.Okved).values(code=item.code, name=item.name)
        await session.execute(
            stmt.on_conflict_do_update(index_elements=[m.Okved.code], set_={"name": item.name})
        )


async def _insert_entity(session: AsyncSession, entity: Card, mixin: dict[str, Any]) -> None:
    common: dict[str, Any] = {
        "inn": entity.inn,
        "type": entity.type,
        "registration_date": entity.registration_date,
        "status_code": entity.status.code,
        "status_name": entity.status.name,
        "status_since": entity.status.since,
        "okved_main": entity.okved_main.code,
        "okved_additional": [o.code for o in entity.okved_additional],
        "tax_authority_code": entity.tax_authority.code,
        "tax_authority_name": entity.tax_authority.name,
        "last_record_grn": entity.last_record.grn,
        "last_record_date": entity.last_record.date,
        **mixin,
    }
    if isinstance(entity, sc.IndividualEntrepreneurCard):
        session.add(
            m.Entity(
                ogrn=entity.ogrnip,
                person_inn=entity.inn,  # ИНН предпринимателя совпадает с ИНН физлица
                region_code=entity.region.code,
                region_name=entity.region.name,
                **common,
            )
        )
        await session.flush()
        return
    session.add(
        m.Entity(
            ogrn=entity.ogrn,
            kpp=entity.kpp,
            full_name=entity.full_name,
            short_name=entity.short_name,
            okopf_code=entity.legal_form.okopf,
            okopf_name=entity.legal_form.name,
            pending_exclusion=_dump(entity.pending_exclusion),
            region_code=entity.address.region_code,
            region_name=entity.address.region_name,
            address_full=entity.address.full,
            address_unreliable=_dump(entity.address.unreliable),
            authorized_capital_rub=entity.authorized_capital_rub,
            **common,
        )
    )
    await session.flush()  # организация должна быть в базе до ссылающихся на неё ролей
    order = 0
    if entity.director is not None:
        session.add(
            m.EntityRole(
                entity_inn=entity.inn,
                role=DIRECTOR,
                person_inn=entity.director.inn,
                position=entity.director.position,
                since=entity.director.since,
                unreliable=_dump(entity.director.unreliable),
                position_order=order,
            )
        )
    for founder in entity.founders:
        order += 1
        is_person = founder.type == "PERSON"
        session.add(
            m.EntityRole(
                entity_inn=entity.inn,
                role=FOUNDER,
                person_inn=founder.inn if is_person else None,
                founder_entity_inn=None if is_person else founder.inn,
                founder_name=None if is_person else founder.full_name,
                share_percent=founder.share_percent,
                share_nominal_rub=founder.share_nominal_rub,
                since=entity.registration_date,
                unreliable=_dump(founder.unreliable),
                position_order=order,
            )
        )
    await session.flush()


# --- список, сценарии, сброс ------------------------------------------------------------------


def _subject_rows(scenario: str | None, origin: Origin | None) -> sa.CompoundSelect[Any]:
    """Субъекты: все организации/ИП и люди, записанные отдельно."""
    entities = sa.select(m.Entity.inn, m.Entity.scenario_code, m.Entity.origin)
    standalone = sa.select(m.Person.inn, m.Person.scenario_code, m.Person.origin).where(
        m.Person.owner_inn == m.Person.inn,
        ~sa.exists().where(m.Entity.inn == m.Person.inn),
    )
    if scenario:
        entities = entities.where(m.Entity.scenario_code == scenario)
        standalone = standalone.where(m.Person.scenario_code == scenario)
    if origin:
        entities = entities.where(m.Entity.origin == origin.value)
        standalone = standalone.where(m.Person.origin == origin.value)
    return sa.union_all(entities, standalone)


async def list_subjects(
    session: AsyncSession, scenario: str | None, origin: Origin | None, limit: int, offset: int
) -> tuple[list[tuple[str, str | None, str, str | None]], int]:
    union = _subject_rows(scenario, origin).subquery()
    total = await session.scalar(sa.select(sa.func.count()).select_from(union))
    page = (
        await session.execute(sa.select(union).order_by(union.c.inn).limit(limit).offset(offset))
    ).all()
    inns = [r.inn for r in page]
    entities = {
        e.inn: e for e in await session.scalars(sa.select(m.Entity).where(m.Entity.inn.in_(inns)))
    }
    people = await _persons(session, inns)
    items: list[tuple[str, str | None, str, str | None]] = []
    for row in page:
        entity = entities.get(row.inn)
        title: str | None = None
        if entity is not None and entity.type == LEGAL_ENTITY:
            title = entity.short_name
        elif (p := people.get(row.inn)) is not None:
            name = person_full_name(p.last_name, p.first_name, p.middle_name)
            title = f"ИП {name}" if entity is not None else name
        items.append((row.inn, row.scenario_code, row.origin, title))
    return items, int(total or 0)


async def scenario_counts(session: AsyncSession) -> list[tuple[str, int]]:
    union = _subject_rows(None, None).subquery()
    rows = await session.execute(
        sa.select(union.c.scenario_code, sa.func.count())
        .where(union.c.scenario_code.is_not(None))
        .group_by(union.c.scenario_code)
        .order_by(union.c.scenario_code)
    )
    return [(code, n) for code, n in rows]


async def delete_scenario(session: AsyncSession, code: str) -> int:
    union = _subject_rows(code, None).subquery()
    inns = list(await session.scalars(sa.select(union.c.inn)))
    for inn in inns:
        await clear_subject(session, inn)
    await session.execute(sa.delete(m.Bankruptcy).where(m.Bankruptcy.scenario_code == code))
    return len(inns)


async def wipe(session: AsyncSession) -> None:
    for table in (m.EntityRole, m.Entity, m.Bankruptcy, m.Person):  # справочник ОКВЭД остаётся
        await session.execute(sa.delete(table))
