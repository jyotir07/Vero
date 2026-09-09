"""What the agent is allowed to call, and from where.

This is the permission half of the propose/execute boundary. The state machine decides
where an application can go; this decides what the agent may do to get it there.

update_application_status is deliberately registered but marked system-only. Leaving it
out entirely would make an agent attempt look like a typo; keeping it visible means the
attempt is refused and recorded as REJECTED_PERMISSION, which is the boundary doing its
job in a way you can point at.
"""

from dataclasses import dataclass

from vero.domain.enums import ApplicationState as S

ALL_STATES = frozenset(S)


class ToolError(Exception):
    """Base for every refusal to run a tool."""


class UnknownToolError(ToolError):
    def __init__(self, name: str) -> None:
        super().__init__(f"no such tool: {name}")
        self.name = name


class ToolNotPermittedError(ToolError):
    def __init__(self, name: str, state: S, reason: str) -> None:
        super().__init__(f"{name} is not permitted in {state}: {reason}")
        self.name = name
        self.state = state
        self.reason = reason


@dataclass(frozen=True)
class ToolSpec:
    name: str
    allowed_states: frozenset[S]
    agent_callable: bool = True


def _spec(name: str, *states: S, agent_callable: bool = True) -> ToolSpec:
    return ToolSpec(name=name, allowed_states=frozenset(states), agent_callable=agent_callable)


REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        # Reading the application is harmless and useful everywhere.
        ToolSpec("get_application", ALL_STATES),
        _spec("extract_document", S.DOCUMENT_CHECK),
        _spec("check_required_documents", S.DOCUMENT_CHECK),
        _spec("request_information", S.DOCUMENT_CHECK),
        _spec("verify_income", S.INCOME_VERIFICATION),
        _spec("calculate_dti", S.CREDIT_ANALYSIS),
        _spec("calculate_affordability", S.CREDIT_ANALYSIS),
        _spec("run_credit_check", S.CREDIT_ANALYSIS),
        _spec("evaluate_policy", S.RISK_ASSESSMENT),
        _spec("create_human_review", S.INCOME_VERIFICATION, S.RISK_ASSESSMENT),
        # System-only: the machine moves applications, model output never does.
        _spec("update_application_status", *ALL_STATES, agent_callable=False),
    )
}


def get_tool(name: str) -> ToolSpec:
    try:
        return REGISTRY[name]
    except KeyError:
        raise UnknownToolError(name) from None


def check_tool_permitted(name: str, *, state: S) -> ToolSpec:
    spec = get_tool(name)
    if not spec.agent_callable:
        raise ToolNotPermittedError(name, state, "system-only tool")
    if state not in spec.allowed_states:
        raise ToolNotPermittedError(name, state, "tool is not available in this state")
    return spec


def tools_available_to_agent(state: S) -> set[str]:
    return {
        name
        for name, spec in REGISTRY.items()
        if spec.agent_callable and state in spec.allowed_states
    }
