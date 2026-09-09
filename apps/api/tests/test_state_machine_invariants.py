"""Structural properties of the transition graph.

These do not restate the edge list. They assert shape, so a future edit that adds a
plausible-looking edge still has to keep the graph well-formed.
"""

import pytest

from vero.domain.enums import ApplicationState as S
from vero.state_machine.machine import successors
from vero.state_machine.transitions import TERMINAL_STATES


def _reachable_from(start: S) -> set[S]:
    seen: set[S] = set()
    queue = [start]
    while queue:
        state = queue.pop()
        for nxt in successors(state):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_terminal_state_has_no_exit(state: S) -> None:
    assert successors(state) == set()


@pytest.mark.parametrize("state", list(S))
def test_no_state_transitions_to_itself(state: S) -> None:
    assert state not in successors(state)


@pytest.mark.parametrize("state", [s for s in S if s is not S.RECEIVED])
def test_every_state_is_reachable_from_received(state: S) -> None:
    assert state in _reachable_from(S.RECEIVED)


@pytest.mark.parametrize("state", [s for s in S if s not in TERMINAL_STATES])
def test_every_state_can_still_reach_a_terminal_state(state: S) -> None:
    assert _reachable_from(state) & TERMINAL_STATES


def test_received_is_the_only_state_with_no_predecessor() -> None:
    has_predecessor = {target for state in S for target in successors(state)}
    assert set(S) - has_predecessor == {S.RECEIVED}
