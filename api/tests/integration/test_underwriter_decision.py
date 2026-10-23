"""T-362/T-364: `pipeline.record_underwriter_decision` на настоящем PostgreSQL (30-11, D-030)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from app.modules import auth, pipeline
from app.modules.applications import Application, ApplicationEvent
from app.modules.auth.models import User
from app.modules.decisioning import UnderwriterTerms
from app.modules.decisioning.types import Level, Outcome, Product
from app.modules.offers import Offer, OfferVariant
from app.modules.pipeline.models import Decision, DecisionReason
from app.shared import clock, db
from app.shared.errors import AppError
from tests.fixtures import core_personas as cases
from tests.integration.test_backoffice_queue import seed

pytestmark = pytest.mark.integration

COMMENT = "Старший андеррайтер проверил документы по залогу и согласовал условия."
SECRET = "строго внутренняя заметка"


@pytest.fixture
def database(postgres_url: str) -> Iterator[db.Database]:
    database = db.configure(postgres_url)
    db.migrate(database.engine)
    with database.transaction() as s:
        s.execute(text("TRUNCATE applications, companies, users, policy_versions CASCADE"))
    fixed = clock.now()
    clock.set_clock(clock.Clock(real_now=lambda: fixed))
    yield database
    clock.set_clock(clock.Clock())
    database.dispose()


def underwriter(level: str) -> UUID:
    with db.transaction() as s:
        user = User(
            login_ref=f"uw-{uuid4()}",
            display_name="Андеррайтер",
            role="UNDERWRITER",
            level=level,
            status="ACTIVE",
        )
        s.add(user)
        s.flush()
        return user.id


def record(app_id: UUID, uw: UUID, **kw: object) -> pipeline.UnderwriterReceipt:
    args: dict[str, object] = {
        "application_id": app_id,
        "expected_version": 3,
        "actor_id": uw,
        "actor_level": Level.L2,
        "outcome": Outcome.APPROVED,
        "terms": UnderwriterTerms(Product.INVESTMENT, 15_000_000, 60),
    }
    args.update(kw)
    with db.transaction() as s:
        return pipeline.record_underwriter_decision(s, **args)  # type: ignore[arg-type]


def record_then_fail(app_id: UUID, uw: UUID) -> None:
    with db.transaction() as s:
        pipeline.record_underwriter_decision(
            s,
            application_id=app_id,
            expected_version=3,
            actor_id=uw,
            actor_level=Level.L2,
            outcome=Outcome.APPROVED,
            terms=UnderwriterTerms(Product.INVESTMENT, 15_000_000, 60),
        )
        raise RuntimeError("откат вызывающего")


def decisions(app_id: UUID) -> list[Decision]:
    with db.transaction() as s:
        rows = list(
            s.scalars(
                select(Decision)
                .where(Decision.application_id == app_id)
                .order_by(Decision.created_at)
            )
        )
        s.expunge_all()
        return rows


def state(app_id: UUID) -> tuple[str, int]:
    with db.transaction() as s:
        a = s.get(Application, app_id)
        assert a is not None
        return a.status, a.version


def events(app_id: UUID) -> list[tuple[str, str | None, str | None]]:
    with db.transaction() as s:
        rows = s.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app_id)
            .order_by(ApplicationEvent.id)
        )
        return [(e.kind, e.step_code, e.to_status) for e in rows]


def test_stankoprom_l2_approves_with_transition_event_offer_and_snapshot(
    database: db.Database,
) -> None:
    app_id = seed("СтанкоПром")
    uw = underwriter("L2")
    receipt = record(app_id, uw, terms=UnderwriterTerms(Product.INVESTMENT, 15_000_000, 60))

    assert (receipt.previous_status, receipt.new_status, receipt.version) == (
        "MANUAL_REVIEW",
        "APPROVED",
        4,
    )
    assert state(app_id) == ("APPROVED", 4)
    assert receipt.deviation is False
    assert "AUTHORITY" in receipt.checked_conditions
    assert receipt.evaluation.payment_rub == 393_247
    engine, human = decisions(app_id)
    assert (engine.source, human.source) == ("ENGINE", "UNDERWRITER")
    assert human.id == receipt.decision_id
    assert receipt.engine_decision_id == engine.id == human.overrides_decision_id
    assert (human.actor_id, human.actor_level, human.deviation) == (uw, "L2", False)
    assert human.inputs_hash == engine.inputs_hash
    assert human.policy_version_id == engine.policy_version_id
    assert human.rate_percent == Decimal("19.500")
    assert human.payment_rub == 393_247
    assert events(app_id)[-3:] == [
        ("TRANSITION", None, "APPROVED"),
        ("STEP", "UNDERWRITER_DECISION", None),
        ("STEP", "OFFER_CREATED", None),
    ]
    with db.transaction() as s:
        offer = s.scalars(select(Offer).where(Offer.application_id == app_id)).one()
        assert (offer.id, offer.decision_id, offer.kind, offer.status) == (
            receipt.offer_id,
            human.id,
            "AS_REQUESTED",
            "OPEN",
        )
        variant = s.scalars(select(OfferVariant).where(OfferVariant.offer_id == offer.id)).one()
        assert (variant.amount_rub, variant.term_months) == (15_000_000, 60)


def test_deviation_emits_override_event_and_hides_comment_from_client(
    database: db.Database,
) -> None:
    app_id = seed("СтанкоПром")
    receipt = record(
        app_id,
        underwriter("L1"),
        actor_level=Level.L1,
        outcome=Outcome.REJECTED,
        terms=None,
        reason_code="UW_RISK_HIGHER",
        comment=SECRET,
    )
    assert receipt.deviation
    assert state(app_id) == ("REJECTED", 4)
    assert events(app_id)[-2] == ("TRANSITION", None, "REJECTED")
    assert events(app_id)[-1][0] == "OVERRIDE"
    _, human = decisions(app_id)
    assert human.override_reason == SECRET
    assert human.override_reason_code == "UW_RISK_HIGHER"
    assert SECRET not in json.dumps(human.explain, ensure_ascii=False)
    with db.transaction() as s:
        assert s.scalars(select(Offer)).all() == []
        codes = [
            r.code
            for r in s.scalars(select(DecisionReason).where(DecisionReason.decision_id == human.id))
        ]
        assert codes == ["UW_RISK_HIGHER"]
        assert s.scalars(
            select(ApplicationEvent.payload).where(ApplicationEvent.kind == "OVERRIDE")
        ).one().get("decisionId") == str(human.id)
        assert SECRET not in json.dumps(
            list(s.scalars(select(ApplicationEvent.payload))), ensure_ascii=False
        )


def test_counter_offer_creates_counter_offer_with_what_changed(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    receipt = record(
        app_id,
        underwriter("L2"),
        outcome=Outcome.COUNTER_OFFER,
        terms=UnderwriterTerms(Product.INVESTMENT, 9_000_000, 48, Decimal("0.2")),
        reason_code="UW_COLLATERAL_ASSESSED",
        comment=COMMENT,
    )
    assert state(app_id) == ("COUNTER_OFFER", 4)
    with db.transaction() as s:
        offer = s.get(Offer, receipt.offer_id)
        assert offer is not None
        assert offer.kind == "COUNTER"
        v = s.scalars(select(OfferVariant).where(OfferVariant.offer_id == offer.id)).one()
        assert (v.amount_rub, v.term_months, v.rate_percent) == (9_000_000, 48, Decimal("20.000"))
        assert v.what_changed["amountRub"] == {"from": 15_000_000, "to": 9_000_000}


def test_stale_version_conflicts_and_writes_nothing(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    with pytest.raises(AppError) as err:
        record(app_id, underwriter("L2"), expected_version=2)
    assert (err.value.status, err.value.code) == (409, "VERSION_CONFLICT")
    assert len(decisions(app_id)) == 1
    assert state(app_id) == ("MANUAL_REVIEW", 3)


def test_repeat_call_is_a_clear_conflict_not_a_second_snapshot(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    uw = underwriter("L2")
    record(app_id, uw)
    with pytest.raises(AppError) as same_version:
        record(app_id, uw)
    assert same_version.value.code == "VERSION_CONFLICT"
    with pytest.raises(AppError) as new_version:
        record(app_id, uw, expected_version=4)
    assert (new_version.value.status, new_version.value.code) == (409, "INVALID_TRANSITION")
    assert len(decisions(app_id)) == 2
    assert len(events(app_id)) == 4  # история, переход, шаг решения, предложение: без повторов


def test_caller_rollback_leaves_no_snapshot_status_event_or_offer(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    before = events(app_id)
    uw = underwriter("L2")
    with pytest.raises(RuntimeError):
        record_then_fail(app_id, uw)
    assert len(decisions(app_id)) == 1
    assert state(app_id) == ("MANUAL_REVIEW", 3)
    assert events(app_id) == before
    with db.transaction() as s:
        assert s.scalars(select(Offer)).all() == []


def test_authority_violation_is_403_and_leaves_no_trace(database: db.Database) -> None:
    app_id = seed("Заря", cases.zarya())  # 20 млн: нужен L2
    with pytest.raises(AppError) as err:
        record(
            app_id,
            underwriter("L1"),
            actor_level=Level.L1,
            terms=UnderwriterTerms(Product.CREDIT_LINE, 20_000_000, 12),
        )
    assert (err.value.status, err.value.code) == (403, "AUTHORITY_LEVEL_TOO_LOW")
    assert err.value.errors == [{"requiredLevel": "L2", "actorLevel": "L1"}]
    assert len(decisions(app_id)) == 1
    assert state(app_id) == ("MANUAL_REVIEW", 3)


def test_invalid_conditions_are_rechecked_on_save(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    with pytest.raises(AppError) as err:
        record(
            app_id,
            underwriter("L2"),
            terms=UnderwriterTerms(Product.INVESTMENT, 15_000_000, 60, Decimal("0.6")),
        )
    assert (err.value.status, err.value.code) == (422, "UNDERWRITER_DECISION_INVALID")
    assert err.value.errors is not None
    assert "RATE_OUT_OF_CORRIDOR" in {e["code"] for e in err.value.errors}
    assert len(decisions(app_id)) == 1


def test_stale_engine_reference_and_missing_application(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    with pytest.raises(AppError) as err:
        record(app_id, underwriter("L2"), engine_decision_id=uuid4())
    assert err.value.code == "ENGINE_DECISION_STALE"
    with pytest.raises(AppError) as missing:
        record(uuid4(), underwriter("L2"))
    assert missing.value.status == 404


def test_preview_checks_without_writing(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    with db.transaction() as s:
        ev = pipeline.preview_underwriter_decision(
            s,
            application_id=app_id,
            actor_level=Level.L2,
            outcome=Outcome.APPROVED,
            terms=UnderwriterTerms(Product.INVESTMENT, 15_000_000, 60),
            expected_version=3,
        )
    assert ev.allowed
    assert ev.application_version == 3
    assert len(decisions(app_id)) == 1
    assert state(app_id) == ("MANUAL_REVIEW", 3)


def test_underwriter_snapshot_is_immutable(database: db.Database) -> None:
    app_id = seed("СтанкоПром")
    receipt = record(app_id, underwriter("L2"))
    with pytest.raises(DBAPIError), db.transaction() as s:
        s.execute(
            update(Decision).where(Decision.id == receipt.decision_id).values(outcome="REJECTED")
        )
    with pytest.raises(DBAPIError), db.transaction() as s:
        s.execute(text("DELETE FROM decisions WHERE id = :i"), {"i": receipt.decision_id})
    assert auth is not None
