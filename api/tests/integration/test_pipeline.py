"""T-270, T-272…T-275: конвейер на настоящем Postgres с заглушками источников (оракул 30-17).

Заглушки отдают ответы «как мок» (`tests/fixtures/pipeline_world.py`), согласия подставляет
тестовая функция вместо `applications.bki_consents` (T-260 в параллельной ветке).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules import auth, pipeline
from app.modules.applications import Application, ApplicationEvent, ApplicationVersion
from app.modules.companies.models import Company
from app.modules.decisioning import decide, input_from_json
from app.modules.decisioning.types import SubjectRole
from app.modules.integrations import Integrations
from app.modules.pipeline import bureau, facts, runner
from app.modules.pipeline.consents import ConsentView
from app.modules.pipeline.models import (
    Decision,
    DecisionReason,
    PipelineRun,
    PolicyVersion,
    SourceSnapshot,
)
from app.modules.pipeline.snapshots import load_records
from app.shared import clock, db
from tests.fixtures import pipeline_world as pw
from tests.fixtures.core_personas import romashka as core_romashka

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 21)


@pytest.fixture
def database(postgres_url: str) -> Iterator[db.Database]:
    database = db.configure(postgres_url)
    db.migrate(database.engine)
    clock.set_clock(clock.Clock(TODAY))
    with database.transaction() as s:
        s.execute(
            text(
                "TRUNCATE applications, company_members, companies, users, policy_versions CASCADE"
            )
        )
    yield database
    clock.set_clock(clock.Clock())
    pipeline.set_consents_provider(None)
    database.dispose()


@dataclass
class Case:
    application_id: UUID
    world: pw.World
    integrations: Integrations
    inn: str


def consents_for(*pairs: tuple[str, str]) -> Callable[..., list[ConsentView]]:
    def provider(_session: Any, _application_id: UUID) -> list[ConsentView]:
        signed = clock.now() - timedelta(minutes=10)
        return [
            ConsentView(f"cns_{inn}", inn, role, signed, date(2027, 4, 21), "LOAN_APPLICATION")
            for inn, role in pairs
        ]

    return provider


def make_application(
    database: db.Database,
    world: pw.World,
    *,
    inn: str,
    kind: str,
    product: str,
    amount: int,
    term: int,
    draft: dict[str, Any] | None = None,
) -> Case:
    with database.transaction() as s:
        company = Company(inn=inn, kind=kind, name=f"Компания {inn}", status="ACTIVE")
        s.add(company)
        s.flush()
        user = auth.upsert_client(
            s, login_ref=f"t:{inn}", display_name="Клиент", person_inn=None, scenario_code=None
        )
        data = {
            "productCode": product,
            "amountRub": amount,
            "termMonths": term,
            "purposeCode": None,
            "draft": draft or {},
        }
        application = Application(
            number="АЗ-2026-000001",
            company_id=company.id,
            created_by=user.id,
            status="SUBMITTED",
            version=2,
            product_code=product,
            amount_rub=amount,
            term_months=term,
            draft={},
            flags=[],
        )
        s.add(application)
        s.flush()
        version = ApplicationVersion(
            application_id=application.id, number=1, reason="SUBMIT", data=data, data_hash="h1"
        )
        s.add(version)
        s.flush()
        application.current_version_id = version.id
        application_id = application.id
    return Case(application_id, world, pw.build_integrations(world), inn)


@pytest.fixture
def sokolova(database: db.Database) -> Case:
    pipeline.set_consents_provider(consents_for((pw.SOKOLOVA_INN, "COMPANY")))
    return make_application(
        database,
        pw.sokolova_world(),
        inn=pw.SOKOLOVA_INN,
        kind="IP",
        product="EXPRESS",
        amount=500_000,
        term=12,
    )


@pytest.fixture
def romashka(database: db.Database) -> Case:
    pipeline.set_consents_provider(
        consents_for((pw.ROMASHKA_INN, "COMPANY"), (pw.ROMASHKA_DIRECTOR, "DIRECTOR"))
    )
    return make_application(
        database,
        pw.romashka_world(),
        inn=pw.ROMASHKA_INN,
        kind="LEGAL",
        product="WORKING_CAPITAL",
        amount=3_000_000,
        term=6,
    )


def decision_of(database: db.Database, application_id: UUID) -> Decision:
    with database.transaction() as s:
        return s.scalars(select(Decision).where(Decision.application_id == application_id)).one()


def status_of(database: db.Database, application_id: UUID) -> str:
    with database.transaction() as s:
        application = s.get(Application, application_id)
        assert application is not None
        return application.status


def events_of(
    database: db.Database, application_id: UUID
) -> list[tuple[str, str | None, str | None]]:
    with database.transaction() as s:
        rows = s.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.id)
        )
        return [(e.kind, e.step_code or e.from_status, e.to_status) for e in rows]


# ---------------------------------------------------------------- оракул 30-17


def test_sokolova_is_approved_with_oracle_numbers(database: db.Database, sokolova: Case) -> None:
    result = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert result == pipeline.RunResult.DONE
    assert status_of(database, sokolova.application_id) == "APPROVED"
    decision = decision_of(database, sokolova.application_id)
    assert decision.outcome == "APPROVED"
    assert decision.grade == "A"
    assert decision.score == 92
    assert decision.rate_percent == Decimal("21.5")
    assert decision.payment_rub is not None
    assert abs(decision.payment_rub - 46_677) <= 1
    assert decision.dscr is not None
    assert abs(decision.dscr - Decimal("1.822")) <= Decimal("0.005")
    assert decision.revenue_monthly_rub == 905_000
    assert decision.free_cash_flow_rub == 90_500
    assert decision.engine_version == "dev"
    # События в правильном порядке: взяли в работу → шаги → решение
    assert events_of(database, sokolova.application_id) == [
        ("TRANSITION", "SUBMITTED", "CHECKING"),
        ("STEP", "COMPLETENESS", None),
        ("STEP", "SOURCES", None),
        ("STEP", "BUREAU", None),
        ("TRANSITION", "CHECKING", "APPROVED"),
        ("STEP", "DECISION", None),
        ("STEP", "OFFER_CREATED", None),
    ]
    # Платный отчёт запрошен ровно один раз; обороты, реестр и ФНС спрошены свежо
    assert sokolova.world.count("credit_bureau:report") == 1
    assert sokolova.world.count("registry:company") == 1


def test_sokolova_decision_snapshot_replays(database: db.Database, sokolova: Case) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    decision = decision_of(database, sokolova.application_id)

    replay = decide(input_from_json(json.dumps(decision.inputs)))

    assert replay.inputs_hash == decision.inputs_hash
    assert replay.outcome.value == decision.outcome
    assert replay.numbers.score_points == 92
    with database.transaction() as s:
        reasons = s.scalars(
            select(DecisionReason).where(DecisionReason.decision_id == decision.id)
        ).all()
        assert [r.code for r in reasons] == list(replay.reason_codes)
        policy = s.get(PolicyVersion, decision.policy_version_id)
        assert policy is not None
        assert policy.version == 1
        run = s.scalars(select(PipelineRun)).one()
        assert (run.status, run.current_step, run.attempts) == ("DONE", "DECISION", 1)
        assert run.finished_at is not None
        assert run.locked_until is None
        snapshot_ids = set(decision.snapshot_ids)
        stored = {r.id for r in s.scalars(select(SourceSnapshot))}
        assert snapshot_ids
        assert snapshot_ids <= stored
        assert decision.explain["numbers"]["score_points"] == 92


def test_romashka_is_rejected_after_bureau(database: db.Database, romashka: Case) -> None:
    pipeline.run_pipeline(romashka.application_id, integrations=romashka.integrations)

    assert status_of(database, romashka.application_id) == "REJECTED"
    decision = decision_of(database, romashka.application_id)
    with database.transaction() as s:
        codes = [
            r.code
            for r in s.scalars(
                select(DecisionReason)
                .where(DecisionReason.decision_id == decision.id)
                .order_by(DecisionReason.position)
            )
        ]
    assert codes[0] == "TAX_ARREARS_HIGH"
    assert codes == list(decide(core_romashka()).reason_codes)
    # тексты причин сохранены в снимке решения (Q-113)
    assert decision.explain["explanations"]
    assert decision.explain["explanations"][0]["client"]
    # D-090: БКИ запрошен по каждому субъекту (компания и директор), затем стоп-факторы
    assert romashka.world.count("credit_bureau:report") == 2


# ---------------------------------------------------------------- недоступность и согласия


def test_registry_unavailable_goes_to_manual_review(database: db.Database, sokolova: Case) -> None:
    sokolova.world.down.add("registry:company")

    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    decision = decision_of(database, sokolova.application_id)
    assert decision.outcome == "MANUAL_REVIEW"
    assert any(r["code"] == "SOURCE_UNAVAILABLE" for r in decision.explain["reasons"])
    with database.transaction() as s:
        down = s.scalars(select(SourceSnapshot).where(SourceSnapshot.status == "UNAVAILABLE")).all()
        assert [d.resource for d in down] == ["registry:company"]


def test_bureau_unavailable_goes_to_manual_review(database: db.Database, sokolova: Case) -> None:
    sokolova.world.down.add("credit_bureau:report")

    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert status_of(database, sokolova.application_id) == "MANUAL_REVIEW"
    decision = decision_of(database, sokolova.application_id)
    assert any(r["code"] == "SOURCE_UNAVAILABLE" for r in decision.explain["reasons"])


def test_no_consent_means_no_bureau_call(database: db.Database, sokolova: Case) -> None:
    pipeline.set_consents_provider(consents_for())

    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert sokolova.world.count("credit_bureau:report") == 0
    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"
    decision = decision_of(database, sokolova.application_id)
    assert any(r["code"] == "DATA_INCOMPLETE" for r in decision.explain["reasons"])


def test_expired_consent_is_not_used(database: db.Database, sokolova: Case) -> None:
    def expired(_s: Any, _a: UUID) -> list[ConsentView]:
        return [
            ConsentView(
                "cns_old",
                pw.SOKOLOVA_INN,
                "COMPANY",
                clock.now() - timedelta(days=300),
                date(2026, 10, 1),
                "LOAN_APPLICATION",
            )
        ]

    pipeline.set_consents_provider(expired)
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert sokolova.world.count("credit_bureau:report") == 0
    assert status_of(database, sokolova.application_id) == "NEEDS_INFO"


# ---------------------------------------------------------------- идемпотентность, аренда, возобновление


def test_second_run_creates_no_second_decision_or_transition(
    database: db.Database, sokolova: Case
) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    before = events_of(database, sokolova.application_id)

    again = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert again == pipeline.RunResult.SKIPPED
    assert events_of(database, sokolova.application_id) == before
    with database.transaction() as s:
        assert len(s.scalars(select(Decision)).all()) == 1
        assert len(s.scalars(select(PipelineRun)).all()) == 1
    assert sokolova.world.count("credit_bureau:report") == 1


def test_lease_blocks_second_worker(database: db.Database, sokolova: Case) -> None:
    first = runner.claim_run(sokolova.application_id)
    second = runner.claim_run(sokolova.application_id)

    assert first is not None
    assert second is None  # чужая аренда: тихо выходим


def test_expired_lease_resumes_from_checkpoint(
    database: db.Database, sokolova: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("воркер умер посреди шага БКИ")

    original = runner.step_bureau
    monkeypatch.setattr(runner, "step_bureau", broken)
    with pytest.raises(RuntimeError):
        pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    monkeypatch.setattr(runner, "step_bureau", original)
    # Аренда ещё жива: второй экземпляр не вмешивается
    assert (
        pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
        == pipeline.RunResult.SKIPPED
    )
    with db.transaction() as s:
        s.execute(text("UPDATE pipeline_runs SET locked_until = now() - interval '1 second'"))
        run = s.scalars(select(PipelineRun)).one()
        assert run.current_step == "SOURCES"

    result = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert result == pipeline.RunResult.DONE
    assert status_of(database, sokolova.application_id) == "APPROVED"
    # Выполненные шаги не повторялись: реестр спрошен один раз
    assert sokolova.world.count("registry:company") == 1
    steps = [e for e in events_of(database, sokolova.application_id) if e[0] == "STEP"]
    assert [s[1] for s in steps] == [
        "COMPLETENESS",
        "SOURCES",
        "BUREAU",
        "DECISION",
        "OFFER_CREATED",
    ]
    with db.transaction() as s:
        assert s.scalars(select(PipelineRun)).one().attempts == 2


def test_lease_lost_aborts_quietly(
    database: db.Database, sokolova: Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = runner.step_sources

    def steal_lease(claim: runner.Claimed, ports: Integrations) -> None:
        with db.transaction() as s:
            s.execute(text("UPDATE pipeline_runs SET lease_token = gen_random_uuid()"))
        original(claim, ports)

    monkeypatch.setattr(runner, "step_sources", steal_lease)

    result = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert result == pipeline.RunResult.LEASE_LOST
    assert status_of(database, sokolova.application_id) == "CHECKING"
    with database.transaction() as s:
        assert s.scalars(select(Decision)).all() == []


def test_withdrawn_application_abandons_run(database: db.Database, sokolova: Case) -> None:
    original = runner.step_bureau

    def withdraw_then_continue(claim: runner.Claimed, ports: Integrations) -> None:
        with db.transaction() as s:
            s.execute(text("UPDATE applications SET status = 'WITHDRAWN', version = version + 1"))
        original(claim, ports)

    runner.step_bureau = withdraw_then_continue  # type: ignore[assignment]
    try:
        result = pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    finally:
        runner.step_bureau = original  # type: ignore[assignment]

    assert result == pipeline.RunResult.ABANDONED
    assert status_of(database, sokolova.application_id) == "WITHDRAWN"
    with database.transaction() as s:
        assert s.scalars(select(Decision)).all() == []
        assert s.scalars(select(PipelineRun)).one().status == "FAILED"


# ---------------------------------------------------------------- БКИ: переиспользование отчёта


def test_bureau_report_is_reused_within_application(database: db.Database, sokolova: Case) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    with database.transaction() as s:
        # Повторный прогон той же заявки (например, после ответа клиента): новая версия
        s.execute(text("UPDATE applications SET status = 'SUBMITTED'"))
        s.add(
            ApplicationVersion(
                application_id=sokolova.application_id,
                number=2,
                reason="INFO_PROVIDED",
                data=s.scalars(select(ApplicationVersion)).one().data,
                data_hash="h2",
            )
        )
        s.flush()
        version = s.scalars(select(ApplicationVersion).where(ApplicationVersion.number == 2)).one()
        s.execute(text("UPDATE applications SET current_version_id = :v"), {"v": version.id})

    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)

    assert sokolova.world.count("credit_bureau:report") == 1  # второго платного запроса нет
    with database.transaction() as s:
        decisions = s.scalars(select(Decision).order_by(Decision.created_at)).all()
        assert len(decisions) == 2
        reports = s.scalars(
            select(SourceSnapshot).where(SourceSnapshot.resource == facts.BKI_REPORT)
        ).all()
        assert len(reports) == 1
        # решение второго запуска ссылается на отчёт первого запуска
        assert reports[0].id in decisions[1].snapshot_ids


def test_report_of_other_application_is_not_reused(database: db.Database, sokolova: Case) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    consents = consents_for((pw.SOKOLOVA_INN, "COMPANY"))(None, sokolova.application_id)
    subject = facts.Subject(SubjectRole.COMPANY, pw.SOKOLOVA_INN, True)

    with database.transaction() as s:
        same = bureau.plan_bureau(s, sokolova.application_id, [subject], consents)
        other = bureau.plan_bureau(s, UUID(int=1), [subject], consents)

    assert [x.inn for x in same.reused] == [pw.SOKOLOVA_INN]
    assert not same.to_request
    assert [x[0].inn for x in other.to_request] == [pw.SOKOLOVA_INN]
    assert not other.reused


# ---------------------------------------------------------------- неизменяемость, политика, задача


def test_snapshots_and_decisions_are_immutable(database: db.Database, romashka: Case) -> None:
    pipeline.run_pipeline(romashka.application_id, integrations=romashka.integrations)

    for statement in (
        "UPDATE source_snapshots SET status = 'OK'",
        "DELETE FROM source_snapshots",
        "UPDATE decisions SET outcome = 'REJECTED'",
        "UPDATE decision_reasons SET code = 'X'",
        "UPDATE policy_versions SET version = 9",
    ):
        with pytest.raises(DBAPIError, match="неизменяем"), database.transaction() as s:
            s.execute(text(statement))


def test_policy_registration_is_idempotent_by_hash(database: db.Database) -> None:
    policy = pipeline.current_policy()
    with database.transaction() as s:
        first = pipeline.register_policy(s, policy)
        second = pipeline.register_policy(s, policy)
        assert first.id == second.id
        changed = policy.model_copy(update={"meta": policy.meta.model_copy(update={"version": 2})})
        third = pipeline.register_policy(s, changed)
        assert third.id != first.id
        assert third.version == 2
        assert len(s.scalars(select(PolicyVersion)).all()) == 2


def test_run_uses_one_policy_version(database: db.Database, sokolova: Case) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    with database.transaction() as s:
        run = s.scalars(select(PipelineRun)).one()
        decision = s.scalars(select(Decision)).one()
        assert run.policy_version_id == decision.policy_version_id


def test_records_are_loaded_back_from_snapshots(database: db.Database, sokolova: Case) -> None:
    pipeline.run_pipeline(sokolova.application_id, integrations=sokolova.integrations)
    with database.transaction() as s:
        run = s.scalars(select(PipelineRun)).one()
        records = load_records(s, run.id, sokolova.application_id)
    assert records.get(facts.BKI_REPORT, pw.SOKOLOVA_INN) is not None
    registry = records.get(facts.REGISTRY, pw.SOKOLOVA_INN)
    assert registry is not None
    assert registry.usable
    loans = records.get(facts.LOANS, pw.SOKOLOVA_INN)
    assert loans is not None
    assert loans.data == ()
