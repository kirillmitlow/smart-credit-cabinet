"""Сборка `decide()` (T-280, T-295, T-300): типы, чистота, приоритет исходов, след, режимы."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.modules.decisioning import (
    DecisionInput,
    decide,
    input_from_json,
    input_to_json,
    inputs_hash,
    policy_hash,
)
from app.modules.decisioning.reasons import CODE_KINDS
from app.modules.decisioning.types import (
    ApplicantKind,
    BkiSubject,
    ComplianceData,
    Mode,
    Outcome,
    RegistryData,
    Route,
    SourceMeta,
    SourceStatus,
    SubjectRole,
    TaxData,
)
from tests.fixtures import core_personas as cp

pytestmark = pytest.mark.unit

D = Decimal


# ---------------------------------------------------------------- сериализация, хеши, детерминизм


@pytest.mark.parametrize("name", sorted(cp.PERSONAS))
def test_input_round_trips_through_json_without_loss(name: str) -> None:
    inp = cp.PERSONAS[name]()
    text = input_to_json(inp)
    restored = input_from_json(text)
    assert restored == inp
    assert input_to_json(restored) == text  # канонический вид стабилен
    assert decide(restored) == decide(inp)  # воспроизведение по сохранённому входу (INV-52)


def test_money_stays_decimal_and_exact_in_json() -> None:
    text = input_to_json(cp.sokolova())
    assert '"0.215"' not in text  # ставка в входе не хранится, а процентные доли политики — строки
    restored = input_from_json(text)
    assert isinstance(restored.policy.pricing.key_rate.value, Decimal)
    assert restored.policy.pricing.key_rate.value == D("0.14")


def test_inputs_hash_is_stable_and_sensitive() -> None:
    inp = cp.sokolova()
    assert inputs_hash(inp) == inputs_hash(input_from_json(input_to_json(inp)))
    bigger = cp.with_application(inp, amount_rub=inp.application.amount_rub + 1)
    assert inputs_hash(bigger) != inputs_hash(inp)
    assert len(inputs_hash(inp)) == 64


def test_policy_version_and_hash_are_in_the_result() -> None:
    result = decide(cp.sokolova())
    assert result.policy_version == 1
    assert result.policy_hash == policy_hash(cp.load_policy())
    assert result.inputs_hash == inputs_hash(cp.sokolova())
    assert result.kind == "FINAL"
    assert result.mode == Mode.DECISION


@pytest.mark.parametrize("name", sorted(cp.PERSONAS))
def test_decide_is_deterministic_including_reason_order_inv_50(name: str) -> None:
    inp = cp.PERSONAS[name]()
    first, second = decide(inp), decide(inp)
    assert first == second
    assert repr(first) == repr(second)
    assert first.reason_codes == second.reason_codes


@pytest.mark.parametrize("name", sorted(cp.PERSONAS))
def test_every_reason_code_comes_from_the_catalog_inv_53(name: str) -> None:
    result = decide(cp.PERSONAS[name]())
    assert all(r.code in CODE_KINDS for r in result.reasons)
    assert all(r.kind == CODE_KINDS[r.code] for r in result.reasons)
    if result.outcome == Outcome.REJECTED:
        assert result.reasons, "у REJECTED причина есть всегда"
    assert len(result.explanations) == len(result.reasons)


def test_decide_is_fast_without_counter_offers() -> None:
    inp = cp.zarya()
    decide(inp)  # прогрев
    started = time.perf_counter()
    for _ in range(10):
        decide(inp)
    assert (time.perf_counter() - started) / 10 < 0.1  # < 100 мс на вызов (T-300)


def test_input_is_immutable() -> None:
    inp = cp.sokolova()
    with pytest.raises(AttributeError):
        inp.application.amount_rub = 1  # type: ignore[misc]
    assert inp.application_id == "APP-SOKOLOVA"


# ---------------------------------------------------------------- допуск и полнота (T-295)


def test_self_employed_is_not_eligible_and_nothing_else_is_computed() -> None:
    result = decide(cp.orlov())
    assert result.outcome == Outcome.NOT_ELIGIBLE
    assert result.reason_codes == ("SELF_EMPLOYED",)
    assert result.features is None
    assert result.numbers.score_points is None
    steps = {s.step: s for s in result.trace}
    assert steps["1.eligibility"].detail["self_employed"] is True
    assert steps["5.stop_factors"].executed is False


def test_registry_miss_without_npd_is_a_data_problem_not_a_refusal() -> None:
    inp = replace(
        cp.orlov(),
        snapshot=replace(
            cp.orlov().snapshot, npd=replace(cp.orlov().snapshot.npd, is_self_employed=False)
        ),
    )
    result = decide(inp)
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.reason_codes[0] == "DATA_INCOMPLETE"


def test_missing_fields_and_unsigned_consents_give_needs_info() -> None:
    inp = cp.sokolova()
    app = replace(
        inp.application, missing_fields=("director_phone",), unsigned_consents=("BKI_DIRECTOR",)
    )
    result = decide(replace(inp, application=app))
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.reason_codes == ("DATA_INCOMPLETE",)
    reason = result.reasons[0]
    assert reason.params["fields"] == "director_phone"
    assert reason.params["consents"] == "BKI_DIRECTOR"
    assert "director_phone" in result.explanations[0].client
    assert result.numbers.score_points is None  # отказ не из-за нехватки данных, скоринга нет


def test_non_positive_amount_or_term_is_incomplete_data() -> None:
    inp = cp.sokolova()
    for changes in ({"amount_rub": 0}, {"term_months": 0}, {"amount_rub": -5}):
        result = decide(cp.with_application(inp, **changes))
        assert result.outcome == Outcome.NEEDS_INFO


def test_revenue_unknown_is_needs_info_never_a_refusal() -> None:
    result = decide(cp.garipov(second_pass=False))
    assert result.outcome == Outcome.NEEDS_INFO
    assert result.reason_codes == ("REVENUE_UNKNOWN",)
    assert result.route == Route.AUTO
    assert result.features is not None
    assert result.features.revenue_cautious_rub is None
    assert "выписку" in result.explanations[0].client


def test_priority_stop_beats_needs_info_beats_everything_else() -> None:
    inp = cp.garipov(second_pass=False)  # NEEDS_INFO
    assert decide(inp).outcome == Outcome.NEEDS_INFO
    aml = ComplianceData(
        cp.ok("c"), (replace(inp.snapshot.compliance.results[0], aml_listed=True),)
    )
    stopped = decide(replace(inp, snapshot=replace(inp.snapshot, compliance=aml)))
    assert stopped.outcome == Outcome.REJECTED
    assert stopped.reason_codes == ("AML_LIST",)
    incomplete = replace(inp, application=replace(inp.application, missing_fields=("x",)))
    assert decide(incomplete).reason_codes == ("DATA_INCOMPLETE", "REVENUE_UNKNOWN")


# ---------------------------------------------------------------- недоступные источники


def test_unavailable_required_source_goes_to_a_human() -> None:
    inp = cp.sokolova()
    snap = replace(inp.snapshot, tax=TaxData(SourceMeta(SourceStatus.UNAVAILABLE)))
    result = decide(replace(inp, snapshot=snap))
    assert result.outcome == Outcome.MANUAL_REVIEW
    assert result.reasons[0].code == "SOURCE_UNAVAILABLE"
    assert result.reasons[0].params["sources"] == "tax"
    assert result.recommendation is not None


def test_unavailable_bki_in_decision_mode_is_a_gap_but_not_in_preview() -> None:
    inp = cp.sokolova()
    gone = tuple(
        BkiSubject(s.role, s.inn, SourceMeta(SourceStatus.UNAVAILABLE)) for s in inp.snapshot.bki
    )
    decision = decide(replace(inp, snapshot=replace(inp.snapshot, bki=gone)))
    assert "SOURCE_UNAVAILABLE" in decision.reason_codes
    preview = decide(
        replace(
            inp,
            snapshot=replace(inp.snapshot, bki=()),
            context=replace(inp.context, mode=Mode.PREVIEW),
        )
    )
    assert "SOURCE_UNAVAILABLE" not in preview.reason_codes


def test_missing_registry_entry_for_company_is_reported() -> None:
    inp = cp.sokolova()
    snap = replace(inp.snapshot, registry=RegistryData(SourceMeta(SourceStatus.UNAVAILABLE)))
    result = decide(replace(inp, snapshot=snap))
    assert "SOURCE_UNAVAILABLE" in result.reason_codes
    assert result.features is not None
    assert result.features.business_age_months is None


def test_contract_product_requires_eis() -> None:
    inp = cp.snabkontrakt()
    app = replace(inp.application, product=cp.Product.CONTRACT, amount_rub=8_000_000, term_months=4)
    gone = replace(inp.snapshot.contracts, meta=SourceMeta(SourceStatus.UNAVAILABLE), contracts=())
    result = decide(replace(inp, application=app, snapshot=replace(inp.snapshot, contracts=gone)))
    assert "SOURCE_UNAVAILABLE" in result.reason_codes
    assert "CONTRACT_INVALID" in result.reason_codes


# ---------------------------------------------------------------- режимы


def test_preview_does_not_promise_more_than_decision() -> None:
    inp = cp.sokolova()
    preview = decide(replace(inp, context=replace(inp.context, mode=Mode.PREVIEW)))
    decision = decide(inp)
    assert preview.mode == Mode.PREVIEW
    assert preview.numbers.score_points is not None
    assert decision.numbers.score_points is not None
    assert preview.numbers.score_points <= decision.numbers.score_points
    assert (preview.numbers.max_amount_rub or 0) <= (decision.numbers.max_amount_rub or 0) + 1
    trace = {s.step: s for s in preview.trace}
    assert trace["7.scoring"].detail["cautious_bki"] is True


def test_product_rules_are_the_same_in_both_modes() -> None:
    inp = cp.with_application(
        cp.sokolova(), product=cp.Product.CREDIT_LINE, amount_rub=2_000_000, term_months=12
    )
    preview = decide(replace(inp, context=replace(inp.context, mode=Mode.PREVIEW)))
    decision = decide(inp)
    kinds = {c for c in decision.reason_codes if CODE_KINDS[c].value == "PRODUCT"}
    assert kinds <= set(preview.reason_codes)


# ---------------------------------------------------------------- след шагов


def test_trace_lists_every_step_with_compared_values() -> None:
    result = decide(cp.snabkontrakt())
    steps = [s.step for s in result.trace]
    assert steps == [
        "1.eligibility",
        "6.features",
        "5.stop_factors",
        "3a.completeness",
        "7.scoring",
        "8.pricing",
        "9.limits",
        "10.product_rules",
        "11.routing",
        "12.counter_offers",
        "13.explanations",
    ]
    limits = next(s for s in result.trace if s.step == "9.limits")
    assert limits.detail["dscr"] == result.numbers.dscr
    assert limits.detail["violations"] == "DSCR_LOW"


def test_trace_marks_skipped_steps_with_the_reason() -> None:
    result = decide(cp.romashka())
    skipped = [s for s in result.trace if not s.executed]
    assert {s.step for s in skipped} >= {"7.scoring", "8.pricing", "9.limits", "11.routing"}
    assert all(s.detail["reason"] == "STOP_FACTOR" for s in skipped)


def test_explanations_follow_the_reasons() -> None:
    result = decide(cp.romashka())
    assert [e.code for e in result.explanations] == list(result.reason_codes)
    assert "1" in result.explanations[0].client
    assert "₽" in result.explanations[0].client


def test_company_kind_helper_values_are_enums() -> None:
    assert ApplicantKind.LEGAL_ENTITY.value == "LEGAL_ENTITY"
    assert SubjectRole.GUARANTOR.value == "GUARANTOR"
    assert date(2026, 10, 21) == cp.TODAY
    assert isinstance(cp.sokolova(), DecisionInput)
