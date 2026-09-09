"""The tool registry is the permission boundary.

docs/00-handoff.md section 5 lists eleven tools. The registry says which of them the
agent may call, and in which state. Anything outside that is refused before it runs.
"""

import pytest

from vero.domain.enums import ApplicationState as S
from vero.tools.registry import (
    REGISTRY,
    ToolNotPermittedError,
    UnknownToolError,
    check_tool_permitted,
    tools_available_to_agent,
)

DOCUMENTED_TOOLS = {
    "extract_document",
    "check_required_documents",
    "calculate_dti",
    "calculate_affordability",
    "verify_income",
    "run_credit_check",
    "evaluate_policy",
    "request_information",
    "create_human_review",
    "get_application",
    "update_application_status",
}


def test_registry_holds_exactly_the_documented_tools() -> None:
    assert set(REGISTRY) == DOCUMENTED_TOOLS


def test_an_unknown_tool_is_refused() -> None:
    with pytest.raises(UnknownToolError):
        check_tool_permitted("drop_all_tables", state=S.DOCUMENT_CHECK)


def test_a_tool_is_permitted_in_its_own_state() -> None:
    check_tool_permitted("extract_document", state=S.DOCUMENT_CHECK)


def test_a_tool_is_refused_outside_its_state() -> None:
    """Extraction belongs to document check; it has no business at decision time."""
    with pytest.raises(ToolNotPermittedError):
        check_tool_permitted("extract_document", state=S.DECISION)


def test_get_application_is_readable_from_every_state() -> None:
    for state in S:
        check_tool_permitted("get_application", state=state)


def test_update_application_status_is_never_available_to_the_agent() -> None:
    """The headline: state changes belong to the machine, not to model output."""
    for state in S:
        with pytest.raises(ToolNotPermittedError):
            check_tool_permitted("update_application_status", state=state)


def test_update_application_status_is_still_registered() -> None:
    """Registered but system-only, so an agent attempt is a recorded refusal."""
    assert REGISTRY["update_application_status"].agent_callable is False


def test_agent_tools_for_document_check() -> None:
    assert tools_available_to_agent(S.DOCUMENT_CHECK) == {
        "check_required_documents",
        "extract_document",
        "get_application",
        "request_information",
    }


def test_terminal_states_offer_the_agent_nothing_but_reading() -> None:
    for state in (S.APPROVED, S.REJECTED, S.FAILED):
        assert tools_available_to_agent(state) == {"get_application"}


def test_every_agent_callable_tool_is_reachable_in_some_state() -> None:
    """A tool the agent can never reach is dead weight in the prompt."""
    reachable = {name for state in S for name in tools_available_to_agent(state)}
    agent_tools = {name for name, spec in REGISTRY.items() if spec.agent_callable}
    assert agent_tools == reachable


def test_every_registered_tool_has_a_handler() -> None:
    """A registered tool with no handler is a KeyError waiting for the agent to find it."""
    from vero.tools.handlers import HANDLERS, PENDING_TOOLS

    assert set(REGISTRY) - PENDING_TOOLS == set(HANDLERS)


def test_pending_tools_are_declared_not_forgotten() -> None:
    """extract_document needs the document store, which arrives with the extractor."""
    from vero.tools.handlers import PENDING_TOOLS

    assert {"extract_document"} == PENDING_TOOLS
    assert set(REGISTRY) >= PENDING_TOOLS
