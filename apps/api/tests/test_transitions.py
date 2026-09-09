"""The transition table is the spine of the system.

DOCUMENTED_EDGES is transcribed from docs/02-agent-workflow.md and docs/plan.md.
It is the requirement; vero.state_machine.transitions is the implementation. They are
kept separate on purpose so drift in either direction fails here.
"""

import itertools

import pytest

from vero.domain.enums import ApplicationState as S
from vero.state_machine.machine import can_transition, successors

DOCUMENTED_EDGES: list[tuple[S, S]] = [
    (S.RECEIVED, S.DOCUMENT_CHECK),
    (S.DOCUMENT_CHECK, S.INCOME_VERIFICATION),
    (S.DOCUMENT_CHECK, S.MORE_INFORMATION_REQUIRED),
    (S.DOCUMENT_CHECK, S.FAILED),
    (S.MORE_INFORMATION_REQUIRED, S.DOCUMENT_CHECK),
    (S.MORE_INFORMATION_REQUIRED, S.FAILED),
    (S.INCOME_VERIFICATION, S.CREDIT_ANALYSIS),
    (S.INCOME_VERIFICATION, S.HUMAN_REVIEW),
    (S.INCOME_VERIFICATION, S.FAILED),
    (S.CREDIT_ANALYSIS, S.RISK_ASSESSMENT),
    (S.CREDIT_ANALYSIS, S.FAILED),
    (S.RISK_ASSESSMENT, S.DECISION),
    (S.RISK_ASSESSMENT, S.HUMAN_REVIEW),
    (S.HUMAN_REVIEW, S.DECISION),
    (S.HUMAN_REVIEW, S.MORE_INFORMATION_REQUIRED),
    (S.DECISION, S.APPROVED),
    (S.DECISION, S.REJECTED),
]

TERMINAL = {S.APPROVED, S.REJECTED, S.FAILED}


@pytest.mark.parametrize(("source", "target"), DOCUMENTED_EDGES)
def test_documented_edge_is_permitted(source: S, target: S) -> None:
    assert can_transition(source, target)


@pytest.mark.parametrize(
    ("source", "target"),
    [pair for pair in itertools.product(S, S) if pair not in DOCUMENTED_EDGES],
)
def test_undocumented_edge_is_rejected(source: S, target: S) -> None:
    assert not can_transition(source, target)


def test_successors_lists_reachable_next_states() -> None:
    assert successors(S.DOCUMENT_CHECK) == {
        S.INCOME_VERIFICATION,
        S.MORE_INFORMATION_REQUIRED,
        S.FAILED,
    }
