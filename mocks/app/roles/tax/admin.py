"""Админ-API mock-tax: тело `taxProfile`, `financials[]`, `sme`, `npd`, `accountBlocks[]`, `contracts[]`
(раздел 8.3)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.admin import AdminHandler, ScenarioCount, SubjectSummary, SubjectView
from app.common.db import Origin
from app.common.problems import ProblemException
from app.roles.tax import schemas as sc
from app.roles.tax import service


def _invalid(detail: str) -> ProblemException:
    return ProblemException(422, "VALIDATION_ERROR", detail)


class TaxHandler(AdminHandler[sc.TaxBody]):
    body_model = sc.TaxBody

    def check(self, inn: str, body: sc.TaxBody) -> None:
        is_individual = len(inn) == 12
        if body.tax_profile is not None:
            if body.tax_profile.inn != inn:
                raise _invalid(
                    f"ИНН профиля {body.tax_profile.inn} не совпадает с ИНН в пути {inn}"
                )
            if is_individual and body.tax_profile.income_expenses is not None:
                raise _invalid("У ИП incomeExpenses = null: бухотчётности у них нет (раздел 5.1)")
        if is_individual and body.financials:
            raise _invalid("У ИП и самозанятого нет бухотчётности: financials должен быть пустым")
        if body.npd is not None and not is_individual:
            raise _invalid("Статус НПД бывает только у человека (ИНН из 12 цифр)")
        years = [f.year for f in body.financials]
        if len(set(years)) != len(years):
            raise _invalid("В financials один год указан дважды")
        numbers = [c.registry_number for c in body.contracts]
        if len(set(numbers)) != len(numbers):
            raise _invalid("В contracts один реестровый номер указан дважды")

    async def put(
        self, session: AsyncSession, inn: str, body: sc.TaxBody, scenario_code: str | None
    ) -> None:
        await service.replace_subject(session, inn, body, scenario_code)

    async def get_body(self, session: AsyncSession, inn: str) -> sc.TaxBody | None:
        return await service.load_body(session, inn)

    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None:
        body = await service.load_body(session, inn)
        info = await service.subject_info(session, inn)
        if body is None or info is None:
            return None
        return SubjectView(
            inn=inn,
            scenario_code=info[0],
            origin=info[1],
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
            SubjectSummary(inn=r.inn, scenario_code=r.scenario_code, origin=r.origin) for r in rows
        ]
        return items, total

    async def delete(self, session: AsyncSession, inn: str) -> bool:
        return await service.delete_subject(session, inn)

    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]:
        return [
            ScenarioCount(scenario_code=code, subjects=n)
            for code, n in await service.scenario_counts(session)
        ]

    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        return await service.delete_scenario(session, code)

    async def wipe(self, session: AsyncSession) -> None:
        await service.wipe(session)
