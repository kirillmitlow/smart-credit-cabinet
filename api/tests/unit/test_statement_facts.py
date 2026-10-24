"""Local-source adapter preserves the core's priority and anomaly rules."""

from dataclasses import replace
from datetime import date

import pytest

from app.modules.decisioning import decide
from app.modules.decisioning.features import compute_features
from app.modules.decisioning.types import FinancialsData, FinancialYear, SourceStatus, TurnoverData
from app.modules.pipeline import facts
from tests.fixtures.core_personas import garipov, ok
from tests.fixtures.pipeline_world import months

pytestmark = pytest.mark.unit
INN = "001300000555"


def statement(incoming: list[int], outgoing: list[int]) -> facts.StatementData:
    record = facts.SourceRecord(
        facts.STATEMENT,
        INN,
        SourceStatus.OK,
        "source-statement",
        date(2026, 9, 30),
        {
            "inn": INN,
            "months": [
                {"month": month, "incomingRub": amount, "outgoingRub": debit}
                for month, amount, debit in zip(
                    months(len(incoming)), incoming, outgoing, strict=True
                )
            ],
        },
    )
    return facts.statement_data(record)


def test_source_priority_and_absent_source() -> None:
    inp = garipov()
    local = statement([700_000] * 12, [600_000] * 12)
    snap = replace(inp.snapshot, statement=local)
    assert compute_features(replace(inp, snapshot=snap)).revenue_source == "CLIENT_UPLOAD"
    official = FinancialsData(ok("official"), (FinancialYear(2025, 8_400_000, 1_000_000, 0),))
    snap = replace(snap, financials=official)
    assert compute_features(replace(inp, snapshot=snap)).revenue_source == "OFFICIAL"
    snap = replace(snap, turnover=TurnoverData(ok("bank"), local.months))
    assert compute_features(replace(inp, snapshot=snap)).revenue_source == "OWN_BANK"
    assert facts.statement_data(None).months == ()
    assert (
        facts.statement_data(
            facts.SourceRecord(facts.STATEMENT, INN, SourceStatus.NOT_FOUND)
        ).months
        == ()
    )


@pytest.mark.parametrize("rule", ["PUMP", "TRANSIT"])
def test_statement_keeps_anomaly_checks_without_inventing_payer_count(rule: str) -> None:
    incoming = [700_000] * 15 + [1_400_000] * 3 if rule == "PUMP" else [700_000] * 12
    outgoing = [amount * 85 // 100 for amount in incoming] if rule == "PUMP" else [699_000] * 12
    inp = garipov()
    inp = replace(inp, snapshot=replace(inp.snapshot, statement=statement(incoming, outgoing)))
    result = decide(inp)
    assert result.features.payers_in_6m_max is None
    assert any(
        reason.code == "TURNOVER_ANOMALY" and reason.params.get("rule") == rule
        for reason in result.reasons
    )
