"""Checks a proposal before anything acts on it.

Runs in a fixed order - shape, then permission - so a rejection always names the first
thing that was wrong. The reason is fed back to the model on a repair attempt, so it has
to be specific enough to act on.
"""

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from vero.agent.schemas import ProposedAction
from vero.domain.enums import ApplicationState, ValidationResult
from vero.tools.registry import ToolNotPermittedError, UnknownToolError, check_tool_permitted

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class Validation:
    result: ValidationResult
    action: ProposedAction | None
    reason: str | None


def _extract_json(raw: str) -> str | None:
    """Pull a JSON object out of whatever the model wrapped it in.

    Models put JSON inside markdown fences or a sentence of preamble. Rejecting that
    would be brittle rather than strict: the content is well formed, the packaging is not.
    """
    fenced = _FENCE.search(raw)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    if start == -1:
        return None
    try:
        _, end = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        return None
    return raw[start : start + end]


def validate_proposal(raw: str, *, state: ApplicationState) -> Validation:
    candidate = _extract_json(raw or "")
    if candidate is None:
        return Validation(ValidationResult.REJECTED_SCHEMA, None, "no JSON object in output")

    try:
        action = ProposedAction.model_validate_json(candidate)
    except ValidationError as exc:
        return Validation(
            ValidationResult.REJECTED_SCHEMA, None, f"output does not match the schema: {exc}"
        )

    try:
        check_tool_permitted(action.tool, state=state)
    except UnknownToolError:
        return Validation(
            ValidationResult.REJECTED_PERMISSION, action, f"{action.tool} is not a known tool"
        )
    except ToolNotPermittedError as exc:
        return Validation(ValidationResult.REJECTED_PERMISSION, action, str(exc))

    return Validation(ValidationResult.ACCEPTED, action, None)
