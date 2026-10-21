"""Админ-API mock-registry: тело `entity` + `persons[]` + `bankruptcies[]` (раздел 8.3)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.admin import AdminHandler, ScenarioCount, SubjectSummary, SubjectView
from app.common.db import Origin
from app.common.problems import ProblemException
from app.roles.registry import schemas as sc
from app.roles.registry import service


def _invalid(detail: str) -> ProblemException:
    return ProblemException(422, "VALIDATION_ERROR", detail)


class RegistryHandler(AdminHandler[sc.RegistryBody]):
    body_model = sc.RegistryBody

    def check(self, inn: str, body: sc.RegistryBody) -> None:
        people = {p.inn: p for p in body.persons}
        if len(people) != len(body.persons):
            raise _invalid("В persons[] один человек указан дважды")
        entity = body.entity
        if entity is None:
            if inn not in people:
                raise _invalid(
                    f"Без entity записывается человек: он должен быть в persons[] (ИНН {inn})"
                )
        elif entity.inn != inn:
            raise _invalid(f"ИНН карточки {entity.inn} не совпадает с ИНН в пути {inn}")

        def person_named(person_inn: str, full_name: str, where: str) -> None:
            person = people.get(person_inn)
            if person is None:
                raise _invalid(f"{where}: человека с ИНН {person_inn} нет в persons[]")
            expected = service.person_full_name(
                person.last_name, person.first_name, person.middle_name
            )
            if full_name != expected:
                raise _invalid(
                    f"{where}: ФИО «{full_name}» не совпадает с persons[] («{expected}»)"
                )

        if isinstance(entity, sc.IndividualEntrepreneurCard):
            person_named(entity.inn, entity.person.full_name, "ИП")
            person = people[entity.inn]
            if (entity.person.last_name, entity.person.first_name, entity.person.middle_name) != (
                person.last_name,
                person.first_name,
                person.middle_name,
            ):
                raise _invalid("ИП: фамилия, имя или отчество не совпадают с persons[]")
        elif isinstance(entity, sc.LegalEntityCard):
            if entity.director is not None:
                person_named(entity.director.inn, entity.director.full_name, "Руководитель")
            for founder in entity.founders:
                if founder.type == "PERSON":
                    person_named(founder.inn, founder.full_name, "Учредитель")

        known = set(people) | ({entity.inn} if entity is not None else set())
        seen: set[tuple[str, str]] = set()
        for case in body.bankruptcies:
            if case.subject_inn not in known:
                raise _invalid(
                    f"Дело {case.case_number}: subjectInn {case.subject_inn} "
                    "не относится к этому телу (нет ни в entity, ни в persons[])"
                )
            expected_type = "LEGAL_ENTITY" if len(case.subject_inn) == 10 else "PERSON"
            if case.subject_type != expected_type:
                raise _invalid(
                    f"Дело {case.case_number}: у ИНН из {len(case.subject_inn)} цифр "
                    f"subjectType = {expected_type}"
                )
            key = (case.subject_inn, case.case_number)
            if key in seen:
                raise _invalid(f"Дело {case.case_number} у {case.subject_inn} указано дважды")
            seen.add(key)

    async def put(
        self, session: AsyncSession, inn: str, body: sc.RegistryBody, scenario_code: str | None
    ) -> None:
        await service.replace_subject(session, inn, body, scenario_code)

    async def get_body(self, session: AsyncSession, inn: str) -> sc.RegistryBody | None:
        return await service.load_body(session, inn)

    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None:
        body = await service.load_body(session, inn)
        origin = await service.subject_origin(session, inn)
        if body is None or origin is None:
            return None
        scenario_code, origin_value = origin
        return SubjectView(
            inn=inn,
            scenario_code=scenario_code,
            origin=origin_value,
            data=body.model_dump(mode="json", by_alias=True),
        )

    async def list_subjects(
        self,
        session: AsyncSession,
        scenario: str | None,
        origin: Origin | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SubjectSummary], int]:
        rows, total = await service.list_subjects(session, scenario, origin, limit, offset)
        items = [
            SubjectSummary(inn=inn, scenario_code=code, origin=org, title=title)
            for inn, code, org, title in rows
        ]
        return items, total

    async def delete(self, session: AsyncSession, inn: str) -> bool:
        if await service.subject_origin(session, inn) is None:
            return False
        await service.clear_subject(session, inn)
        return True

    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]:
        return [
            ScenarioCount(scenario_code=code, subjects=n)
            for code, n in await service.scenario_counts(session)
        ]

    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        return await service.delete_scenario(session, code)

    async def wipe(self, session: AsyncSession) -> None:
        await service.wipe(session)
