"""Who is allowed to drive each transition.

This is the propose/execute boundary from docs/00-handoff.md section 3 expressed as
data: the agent may advance document checking, but it can never decide an application
and it can never stand in for a reviewer.
"""

import pytest

from vero.domain.enums import Actor
from vero.domain.enums import ApplicationState as S
from vero.state_machine.machine import (
    TransitionNotPermittedError,
    apply_transition,
    transition_actor,
)

DOCUMENTED_ACTORS: dict[tuple[S, S], Actor] = {
    (S.RECEIVED, S.DOCUMENT_CHECK): Actor.SYSTEM,
    (S.DOCUMENT_CHECK, S.INCOME_VERIFICATION): Actor.AGENT,
    (S.DOCUMENT_CHECK, S.MORE_INFORMATION_REQUIRED): Actor.AGENT,
    (S.DOCUMENT_CHECK, S.FAILED): Actor.SYSTEM,
    (S.MORE_INFORMATION_REQUIRED, S.DOCUMENT_CHECK): Actor.APPLICANT,
    (S.MORE_INFORMATION_REQUIRED, S.FAILED): Actor.SYSTEM,
    (S.INCOME_VERIFICATION, S.CREDIT_ANALYSIS): Actor.SYSTEM,
    (S.INCOME_VERIFICATION, S.HUMAN_REVIEW): Actor.SYSTEM,
    (S.INCOME_VERIFICATION, S.FAILED): Actor.SYSTEM,
    (S.CREDIT_ANALYSIS, S.RISK_ASSESSMENT): Actor.SYSTEM,
    (S.CREDIT_ANALYSIS, S.FAILED): Actor.SYSTEM,
    (S.RISK_ASSESSMENT, S.DECISION): Actor.SYSTEM,
    (S.RISK_ASSESSMENT, S.HUMAN_REVIEW): Actor.SYSTEM,
    (S.HUMAN_REVIEW, S.DECISION): Actor.REVIEWER,
    (S.HUMAN_REVIEW, S.MORE_INFORMATION_REQUIRED): Actor.REVIEWER,
    (S.DECISION, S.APPROVED): Actor.SYSTEM,
    (S.DECISION, S.REJECTED): Actor.SYSTEM,
}


@pytest.mark.parametrize(("edge", "actor"), list(DOCUMENTED_ACTORS.items()))
def test_edge_is_owned_by_the_documented_actor(edge: tuple[S, S], actor: Actor) -> None:
    assert transition_actor(*edge) is actor


@pytest.mark.parametrize(("edge", "actor"), list(DOCUMENTED_ACTORS.items()))
def test_owning_actor_may_apply_its_edge(edge: tuple[S, S], actor: Actor) -> None:
    assert apply_transition(*edge, actor=actor) is edge[1]


@pytest.mark.parametrize(
    ("edge", "owner"),
    [(e, a) for e, a in DOCUMENTED_ACTORS.items() if a is not Actor.AGENT],
)
def test_agent_may_not_apply_an_edge_it_does_not_own(edge: tuple[S, S], owner: Actor) -> None:
    with pytest.raises(TransitionNotPermittedError):
        apply_transition(*edge, actor=Actor.AGENT)


def test_agent_cannot_approve_an_application() -> None:
    """The headline property: no model output can reach APPROVED."""
    with pytest.raises(TransitionNotPermittedError):
        apply_transition(S.DECISION, S.APPROVED, actor=Actor.AGENT)


def test_agent_cannot_stand_in_for_a_reviewer() -> None:
    with pytest.raises(TransitionNotPermittedError):
        apply_transition(S.HUMAN_REVIEW, S.DECISION, actor=Actor.AGENT)
