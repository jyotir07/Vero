import pytest

from vero.domain.enums import Actor
from vero.domain.enums import ApplicationState as S
from vero.state_machine.machine import (
    IllegalTransitionError,
    TransitionError,
    TransitionNotPermittedError,
    apply_transition,
)


def test_apply_transition_returns_the_target_state() -> None:
    assert apply_transition(S.RECEIVED, S.DOCUMENT_CHECK, actor=Actor.SYSTEM) is S.DOCUMENT_CHECK


def test_apply_transition_rejects_an_illegal_edge() -> None:
    with pytest.raises(IllegalTransitionError):
        apply_transition(S.DOCUMENT_CHECK, S.APPROVED, actor=Actor.SYSTEM)


def test_illegal_transition_error_names_both_states() -> None:
    with pytest.raises(IllegalTransitionError) as excinfo:
        apply_transition(S.DOCUMENT_CHECK, S.APPROVED, actor=Actor.SYSTEM)
    assert "DOCUMENT_CHECK" in str(excinfo.value)
    assert "APPROVED" in str(excinfo.value)


def test_an_illegal_edge_is_illegal_for_every_actor() -> None:
    """Permission is checked after legality, so no actor unlocks a missing edge."""
    for actor in Actor:
        with pytest.raises(IllegalTransitionError):
            apply_transition(S.RECEIVED, S.APPROVED, actor=actor)


def test_permission_error_names_the_owning_actor() -> None:
    with pytest.raises(TransitionNotPermittedError) as excinfo:
        apply_transition(S.DECISION, S.APPROVED, actor=Actor.AGENT)
    assert excinfo.value.owner is Actor.SYSTEM
    assert excinfo.value.actor is Actor.AGENT


def test_both_refusals_share_a_base_so_callers_can_catch_either() -> None:
    assert issubclass(IllegalTransitionError, TransitionError)
    assert issubclass(TransitionNotPermittedError, TransitionError)
