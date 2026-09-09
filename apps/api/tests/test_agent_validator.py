"""Validation of what the model proposes.

Model output is untrusted input. Everything it can get wrong - malformed JSON, a tool
that does not exist, a tool it may not use here, arguments of the wrong shape - has to
end in a recorded refusal rather than an exception or, worse, an execution.
"""

import pytest

from vero.agent.validator import validate_proposal
from vero.domain.enums import ApplicationState as S
from vero.domain.enums import ValidationResult


def test_a_well_formed_proposal_is_accepted() -> None:
    validation = validate_proposal(
        '{"tool": "check_required_documents", "arguments": {}, "reasoning": "see what is here"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.result is ValidationResult.ACCEPTED
    assert validation.action is not None
    assert validation.action.tool == "check_required_documents"


def test_arguments_are_optional() -> None:
    validation = validate_proposal(
        '{"tool": "check_required_documents", "reasoning": "look"}', state=S.DOCUMENT_CHECK
    )
    assert validation.result is ValidationResult.ACCEPTED
    assert validation.action is not None
    assert validation.action.arguments == {}


def test_malformed_json_is_a_schema_rejection() -> None:
    validation = validate_proposal("not json at all", state=S.DOCUMENT_CHECK)
    assert validation.result is ValidationResult.REJECTED_SCHEMA
    assert validation.action is None


def test_json_that_is_not_an_object_is_rejected() -> None:
    validation = validate_proposal('["check_required_documents"]', state=S.DOCUMENT_CHECK)
    assert validation.result is ValidationResult.REJECTED_SCHEMA


def test_a_missing_tool_field_is_rejected() -> None:
    validation = validate_proposal('{"reasoning": "I forgot the tool"}', state=S.DOCUMENT_CHECK)
    assert validation.result is ValidationResult.REJECTED_SCHEMA


def test_arguments_of_the_wrong_type_are_rejected() -> None:
    validation = validate_proposal(
        '{"tool": "extract_document", "arguments": "doc-1", "reasoning": "x"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.result is ValidationResult.REJECTED_SCHEMA


def test_an_unknown_tool_is_a_permission_rejection() -> None:
    validation = validate_proposal(
        '{"tool": "wire_money_to_me", "arguments": {}, "reasoning": "trust me"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.result is ValidationResult.REJECTED_PERMISSION


def test_a_real_tool_in_the_wrong_state_is_a_permission_rejection() -> None:
    validation = validate_proposal(
        '{"tool": "evaluate_policy", "arguments": {}, "reasoning": "decide now"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.result is ValidationResult.REJECTED_PERMISSION


def test_the_agent_cannot_propose_moving_the_application() -> None:
    """The headline refusal: state changes are not the model's to make."""
    validation = validate_proposal(
        '{"tool": "update_application_status", "arguments": {"to_state": "APPROVED"},'
        ' "reasoning": "looks fine to me"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.result is ValidationResult.REJECTED_PERMISSION
    assert validation.reason is not None
    assert "system-only" in validation.reason


def test_a_rejection_explains_itself_for_the_repair_attempt() -> None:
    """The reason is fed back to the model, so it has to say what was wrong."""
    validation = validate_proposal(
        '{"tool": "evaluate_policy", "arguments": {}, "reasoning": "x"}',
        state=S.DOCUMENT_CHECK,
    )
    assert validation.reason
    assert "evaluate_policy" in validation.reason


def test_empty_output_is_a_schema_rejection() -> None:
    assert validate_proposal("", state=S.DOCUMENT_CHECK).result is ValidationResult.REJECTED_SCHEMA


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"tool": "get_application", "reasoning": "read"}\n```',
        '```\n{"tool": "get_application", "reasoning": "read"}\n```',
        'Here you go:\n{"tool": "get_application", "reasoning": "read"}',
    ],
)
def test_json_wrapped_in_prose_or_fences_is_still_read(raw: str) -> None:
    """Models wrap JSON in markdown. Refusing that would be brittle, not strict."""
    assert validate_proposal(raw, state=S.DOCUMENT_CHECK).result is ValidationResult.ACCEPTED
