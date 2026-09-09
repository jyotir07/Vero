"""Scripted provider for tests, CI, and offline development.

A script is a list of answers to give in order. An entry may be an exception, so a test
can put a timeout exactly where it wants one instead of monkeypatching the transport.
"""

from collections.abc import Callable, Sequence

from vero.agent.provider.base import LLMError, LLMResponse


class ScriptExhausted(LLMError):
    """The runner asked for more turns than the script provides.

    Loud on purpose: repeating the last answer would turn a runaway loop into something
    that looks like it terminated normally.
    """


class FakeLLMProvider:
    def __init__(self, responses: Sequence[str | Exception]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        if self._index >= len(self._responses):
            raise ScriptExhausted(f"script had {len(self._responses)} responses")

        item = self._responses[self._index]
        self._index += 1
        if isinstance(item, Exception):
            raise item

        return LLMResponse(
            content=item,
            model="fake",
            latency_ms=0,
            prompt_tokens=len(system) + len(user),
            completion_tokens=len(item),
        )


class ProgrammableLLMProvider:
    """Answers according to a function of the prompt.

    Runner tests need an agent that reacts to whatever state it is in. A fixed script
    would have to match the exact number of turns, so adding a step would break every
    test rather than the one that changed.
    """

    def __init__(self, responder: Callable[[str, str], str | Exception]) -> None:
        self._responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        answer = self._responder(system, user)
        if isinstance(answer, Exception):
            raise answer
        return LLMResponse(
            content=answer,
            model="fake",
            latency_ms=0,
            prompt_tokens=len(system) + len(user),
            completion_tokens=len(answer),
        )
