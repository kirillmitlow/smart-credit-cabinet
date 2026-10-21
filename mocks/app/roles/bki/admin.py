"""Админ-API данных mock-credit-bureau (раздел 8.3): хранение тела субъекта.

PUT заменяет данные сценария (origin = SCENARIO), а RUNTIME-записи (наши запросы, сведения от банка)
не трогает: переприменение сценария не стирает историю работы. Стирают их DELETE субъекта,
DELETE сценария и wipe.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.admin import (
    AdminHandler,
    ScenarioCount,
    SubjectSummary,
    SubjectView,
    make_admin_router,
)
from app.common.db import Origin
from app.common.idempotency import idempotency_keys
from app.common.problems import ProblemException
from app.roles.bki import models, service
from app.roles.bki import schemas as s


def _invalid(message: str, loc: list[str | int]) -> ProblemException:
    return ProblemException(
        422, "VALIDATION_ERROR", message, errors=[{"loc": ["body", *loc], "msg": message}]
    )


def _title(row: models.Subject) -> str | None:
    if row.name:
        return row.name
    parts = [row.last_name, row.first_name, row.middle_name]
    return " ".join(p for p in parts if p) or None


def _obligation_schema(row: models.Obligation) -> s.AdminObligation:
    return s.AdminObligation(
        uid=row.uid,
        kind=s.ObligationKind(row.kind),
        role=s.ObligationRole(row.role),
        opened_at=row.opened_at,
        planned_close_at=row.planned_close_at,
        closed_at=row.closed_at,
        amount_rub=row.amount_rub,
        limit_rub=row.limit_rub,
        balance_rub=row.balance_rub,
        monthly_payment_rub=row.monthly_payment_rub,
        overdue_rub=row.overdue_rub,
        overdue_periods=[
            s.OverduePeriod(since=p.since, until=p.until) for p in service.periods_of(row)
        ],
        status=s.ObligationStatus(row.status),
        secured=row.secured,
        payment_history=(
            None
            if row.payment_history_fixed is None
            else [s.PaymentMonth.model_validate(m) for m in row.payment_history_fixed]
        ),
    )


def _inquiry_schema(row: models.Inquiry) -> s.AdminInquiry:
    return s.AdminInquiry(
        date=service.msk_date(row.inquired_at),
        user_type=s.UserType(row.user_type),
        purpose=row.purpose,
        is_own=row.is_own,
    )


def _application_schema(row: models.ApplicationInfo) -> s.AdminApplication:
    return s.AdminApplication(
        date=row.applied_at,
        kind=row.kind,
        amount_rub=row.amount_rub,
        decision=s.ApplicationDecision(row.decision),
        decision_date=row.decided_at,
        is_own=row.is_own,
    )


def _bankruptcy_schema(row: models.Bankruptcy) -> s.AdminBankruptcy:
    return s.AdminBankruptcy(
        case_number=row.case_number,
        stage=s.BankruptcyStage(row.stage),
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _dump(model: Any) -> dict[str, Any]:
    dumped: dict[str, Any] = model.model_dump(mode="json", by_alias=True)
    return dumped


class BkiAdminHandler(AdminHandler[s.BkiSubjectBody]):
    body_model = s.BkiSubjectBody

    def check(self, inn: str, body: s.BkiSubjectBody) -> None:
        if body.subject.inn != inn:
            raise _invalid(
                f"subject.inn {body.subject.inn} не совпадает с ИНН в пути {inn}",
                ["subject", "inn"],
            )
        service.check_subject(body.subject)
        uids = [o.uid for o in body.obligations]
        for index, uid in enumerate(uids):
            if uids.count(uid) > 1:
                raise _invalid(
                    f"uid {uid} повторяется в obligations", ["obligations", index, "uid"]
                )
        for index, o in enumerate(body.obligations):
            for p_index, p in enumerate(o.overdue_periods):
                if p.until is not None and p.until < p.since:
                    raise _invalid(
                        "until раньше since", ["obligations", index, "overduePeriods", p_index]
                    )
            if o.closed_at is not None and o.closed_at < o.opened_at:
                raise _invalid("closedAt раньше openedAt", ["obligations", index, "closedAt"])
        for index, bankruptcy in enumerate(body.bankruptcies):
            if bankruptcy.completed_at and bankruptcy.completed_at < bankruptcy.started_at:
                raise _invalid(
                    "completedAt раньше startedAt", ["bankruptcies", index, "completedAt"]
                )

    async def put(
        self, session: AsyncSession, inn: str, body: s.BkiSubjectBody, scenario_code: str | None
    ) -> None:
        subject = body.subject
        values = {
            "type": subject.type.value,
            "ogrn": subject.ogrn,
            "name": subject.name,
            "last_name": subject.last_name,
            "first_name": subject.first_name,
            "middle_name": subject.middle_name,
            "birth_date": subject.birth_date,
            "origin": Origin.SCENARIO.value,
            "scenario_code": scenario_code,
        }
        row = await service.find_subject(session, inn)
        if row is None:
            row = models.Subject(inn=inn, **values)
            session.add(row)
            await session.flush()
        else:
            for key, value in values.items():
                setattr(row, key, value)

        # Запросы, оставленные до появления субъекта (NOT_FOUND), привязываем к нему
        await session.execute(
            sa.update(models.Inquiry)
            .where(models.Inquiry.inn == inn, models.Inquiry.subject_id.is_(None))
            .values(subject_id=row.id)
        )

        # Чужой uid занять нельзя: он уникален на всю базу
        uids = [o.uid for o in body.obligations]
        if uids:
            foreign = await session.scalar(
                sa.select(models.Obligation.uid).where(
                    models.Obligation.uid.in_(uids), models.Obligation.subject_id != row.id
                )
            )
            if foreign:
                raise _invalid(f"uid {foreign} уже принадлежит другому субъекту", ["obligations"])

        # Заменяются данные сценария и записи с теми же uid; RUNTIME-записи остаются
        sid = row.id
        await session.execute(
            sa.delete(models.Obligation).where(
                models.Obligation.subject_id == sid,
                sa.or_(
                    models.Obligation.origin == Origin.SCENARIO.value,
                    models.Obligation.uid.in_(uids),
                ),
            )
        )
        for model in (models.ApplicationInfo, models.Bankruptcy):
            await session.execute(
                sa.delete(model).where(
                    model.subject_id == sid, model.origin == Origin.SCENARIO.value
                )
            )
        await session.execute(
            sa.delete(models.Inquiry).where(
                models.Inquiry.inn == inn, models.Inquiry.origin == Origin.SCENARIO.value
            )
        )

        common: dict[str, Any] = {"origin": Origin.SCENARIO.value, "scenario_code": scenario_code}
        session.add_all(
            models.Obligation(
                subject_id=sid,
                uid=o.uid,
                kind=o.kind.value,
                role=o.role.value,
                opened_at=o.opened_at,
                planned_close_at=o.planned_close_at,
                closed_at=o.closed_at,
                amount_rub=o.amount_rub,
                limit_rub=o.limit_rub,
                balance_rub=o.balance_rub,
                monthly_payment_rub=o.monthly_payment_rub,
                overdue_rub=o.overdue_rub,
                overdue_periods=[_dump(p) for p in o.overdue_periods],
                status=o.status.value,
                secured=o.secured,
                payment_history_fixed=(
                    None if o.payment_history is None else [_dump(m) for m in o.payment_history]
                ),
                **common,
            )
            for o in body.obligations
        )
        session.add_all(
            models.Inquiry(
                inn=inn,
                subject_id=sid,
                inquired_at=service.day_to_moment(i.date),
                user_name=None,
                user_type=i.user_type.value,
                purpose=i.purpose,
                is_own=i.is_own,
                **common,
            )
            for i in body.inquiries
        )
        # Ссылки заявок из сценария синтетические: в теле их нет, нумеруем по порядку
        session.add_all(
            models.ApplicationInfo(
                subject_id=sid,
                application_ref=f"EXT-{index:03d}",
                applied_at=a.date,
                kind=a.kind,
                amount_rub=a.amount_rub,
                decision=a.decision.value,
                decided_at=a.decision_date,
                is_own=a.is_own,
                **common,
            )
            for index, a in enumerate(body.applications, start=1)
        )
        session.add_all(
            models.Bankruptcy(
                subject_id=sid,
                case_number=b.case_number,
                started_at=b.started_at,
                completed_at=b.completed_at,
                stage=b.stage.value,
                **common,
            )
            for b in body.bankruptcies
        )
        await session.flush()

    async def get_body(self, session: AsyncSession, inn: str) -> s.BkiSubjectBody | None:
        records = await service.load_records(session, inn)
        if records.subject is None:
            return None
        scenario = Origin.SCENARIO.value
        return s.BkiSubjectBody(
            subject=service.subject_schema(records.subject),
            obligations=[
                _obligation_schema(o) for o in records.obligations if o.origin == scenario
            ],
            inquiries=[_inquiry_schema(i) for i in records.inquiries if i.origin == scenario],
            applications=[
                _application_schema(a) for a in records.applications if a.origin == scenario
            ],
            bankruptcies=[
                _bankruptcy_schema(b) for b in records.bankruptcies if b.origin == scenario
            ],
        )

    async def view(self, session: AsyncSession, inn: str) -> SubjectView | None:
        records = await service.load_records(session, inn)
        row = records.subject
        if row is None:
            return None
        body = await self.get_body(session, inn)
        if body is None:
            return None
        runtime = Origin.RUNTIME.value
        reports = await session.scalars(
            sa.select(models.Report.id)
            .where(models.Report.inn == inn)
            .order_by(models.Report.generated_at)
        )
        submissions = await session.scalars(
            sa.select(models.Submission.payload)
            .where(models.Submission.inn == inn)
            .order_by(models.Submission.received_at)
        )
        return SubjectView(
            inn=inn,
            scenario_code=row.scenario_code,
            origin=row.origin,
            data=_dump(body),
            runtime={
                "obligations": [
                    _dump(_obligation_schema(o)) for o in records.obligations if o.origin == runtime
                ],
                "inquiries": [
                    _dump(_inquiry_schema(i)) for i in records.inquiries if i.origin == runtime
                ],
                "applications": [
                    _dump(_application_schema(a)) | {"ref": a.application_ref}
                    for a in records.applications
                    if a.origin == runtime
                ],
                "reports": list(reports),
                "submissions": list(submissions),
            },
        )

    async def list_subjects(
        self,
        session: AsyncSession,
        scenario: str | None,
        origin: Origin | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SubjectSummary], int]:
        query = sa.select(models.Subject)
        if scenario:
            query = query.where(models.Subject.scenario_code == scenario)
        if origin:
            query = query.where(models.Subject.origin == origin.value)
        total = await session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
        rows = await session.scalars(query.order_by(models.Subject.inn).limit(limit).offset(offset))
        items = [
            SubjectSummary(
                inn=r.inn,
                scenario_code=r.scenario_code,
                origin=r.origin,
                title=_title(r),
            )
            for r in rows
        ]
        return items, int(total or 0)

    async def delete(self, session: AsyncSession, inn: str) -> bool:
        if await service.find_subject(session, inn) is None:
            return False
        await service.purge_subject_records(session, [inn])
        return True

    async def scenarios(self, session: AsyncSession) -> list[ScenarioCount]:
        rows = await session.execute(
            sa.select(models.Subject.scenario_code, sa.func.count())
            .where(models.Subject.scenario_code.is_not(None))
            .group_by(models.Subject.scenario_code)
            .order_by(models.Subject.scenario_code)
        )
        return [ScenarioCount(scenario_code=code, subjects=n) for code, n in rows]

    async def delete_scenario(self, session: AsyncSession, code: str) -> int:
        inns = list(
            await session.scalars(
                sa.select(models.Subject.inn).where(models.Subject.scenario_code == code)
            )
        )
        await service.purge_subject_records(session, inns)
        return len(inns)

    async def wipe(self, session: AsyncSession) -> None:
        # Порядок важен из-за внешних ключей; ключи идемпотентности чистим вместе с данными,
        # иначе повтор старого запроса вернул бы ответ о данных, которых уже нет
        for model in (
            models.Inquiry,
            models.Report,
            models.Submission,
            models.Obligation,
            models.ApplicationInfo,
            models.Bankruptcy,
            models.Subject,
        ):
            await session.execute(sa.delete(model))
        await session.execute(sa.delete(idempotency_keys))


admin_router = make_admin_router(BkiAdminHandler())
