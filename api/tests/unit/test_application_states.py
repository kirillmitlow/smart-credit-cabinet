"""T-251: таблица переходов = диаграмма 20-02; достижимость конечных статусов; запрещённые пары."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.modules.applications.states import (
    TERMINAL,
    TRANSITIONS,
    Actor,
    Status,
    is_allowed,
    mermaid_edges,
)

pytestmark = pytest.mark.unit

DOC = Path(__file__).resolve().parents[3] / "docs/plan/20-process/02-application-states.md"


def doc_edges() -> set[tuple[str, str]]:
    block = DOC.read_text(encoding="utf-8").split("```mermaid", 1)[1].split("```", 1)[0]
    edges = set(re.findall(r"^\s*([A-Z_]+) --> ([A-Z_]+)", block, re.M))
    return {(a, b) for a, b in edges}


def test_code_table_matches_documented_diagram() -> None:
    assert mermaid_edges() == doc_edges()


def test_every_status_can_reach_a_terminal_one() -> None:
    graph: dict[Status, set[Status]] = {s: set() for s in Status}
    for a, b in TRANSITIONS:
        graph[a].add(b)
    for start in Status:
        seen, stack = {start}, [start]
        while stack:
            for nxt in graph[stack.pop()] - seen:
                seen.add(nxt)
                stack.append(nxt)
        assert seen & TERMINAL, f"Из {start} не достичь конечного статуса"


def test_terminal_statuses_have_no_exits_and_signed_cannot_be_withdrawn() -> None:
    assert not any(a in TERMINAL for a, _ in TRANSITIONS)
    for status in (Status.SIGNED, Status.DISBURSING):
        assert not is_allowed(status, Status.WITHDRAWN, Actor.CLIENT)


def test_forbidden_pairs_are_the_vast_majority() -> None:
    forbidden = [(a, b) for a in Status for b in Status if (a, b) not in TRANSITIONS]
    assert len(forbidden) == 14 * 14 - len(TRANSITIONS)
    assert len(forbidden) > 160


@given(
    st.lists(st.tuples(st.sampled_from(list(Status)), st.sampled_from(list(Actor))), max_size=30)
)
def test_random_walk_only_follows_table(steps: list[tuple[Status, Actor]]) -> None:
    current = Status.DRAFT
    for target, actor in steps:
        if is_allowed(current, target, actor):
            assert (current, target) in TRANSITIONS
            current = target
    assert current in Status
