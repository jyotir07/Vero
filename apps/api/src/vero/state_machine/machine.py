from vero.domain.enums import Actor, ApplicationState
from vero.state_machine.transitions import LEGAL_TRANSITIONS, TRANSITION_ACTORS


class TransitionError(Exception):
    """Base for every refusal to move an application between states."""


class IllegalTransitionError(TransitionError):
    def __init__(self, source: ApplicationState, target: ApplicationState) -> None:
        super().__init__(f"illegal transition {source} -> {target}")
        self.source = source
        self.target = target


class TransitionNotPermittedError(TransitionError):
    def __init__(
        self,
        source: ApplicationState,
        target: ApplicationState,
        actor: Actor,
        owner: Actor,
    ) -> None:
        super().__init__(f"{actor} may not drive {source} -> {target}; owned by {owner}")
        self.source = source
        self.target = target
        self.actor = actor
        self.owner = owner


def can_transition(source: ApplicationState, target: ApplicationState) -> bool:
    return (source, target) in LEGAL_TRANSITIONS


def successors(source: ApplicationState) -> set[ApplicationState]:
    return {target for origin, target in LEGAL_TRANSITIONS if origin == source}


def transition_actor(source: ApplicationState, target: ApplicationState) -> Actor:
    try:
        return TRANSITION_ACTORS[(source, target)]
    except KeyError:
        raise IllegalTransitionError(source, target) from None


def apply_transition(
    source: ApplicationState, target: ApplicationState, *, actor: Actor
) -> ApplicationState:
    owner = transition_actor(source, target)
    if actor is not owner:
        raise TransitionNotPermittedError(source, target, actor, owner)
    return target
