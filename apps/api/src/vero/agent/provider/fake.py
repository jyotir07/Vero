"""Scripted provider for tests, CI, and offline development.

A script is a list of answers to give in order. An entry may be an exception, so a test
can put a timeout exactly where it wants one instead of monkeypatching the transport.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

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


class OfflineAgentProvider:
    """A rule-based stand-in for the model, so the system runs with no API key.

    This is not a language model and does not pretend to be one. It reads the same
    structured prompt the real provider gets and returns the obvious next action for the
    state it is shown, which is enough to drive the workflow end to end offline.

    It exists so that the default configuration produces a working demo rather than a
    broken one, and so that tests and the running server exercise the same agent
    behaviour instead of two separate approximations of it.
    """

    model_name = "offline-rules"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append((system, user))
        answer = json.dumps(self._decide(json.loads(user)))
        return LLMResponse(
            content=answer,
            model=self.model_name,
            latency_ms=0,
            prompt_tokens=len(system) + len(user),
            completion_tokens=len(answer),
        )

    @staticmethod
    def _decide(prompt: dict[str, Any]) -> dict[str, Any]:
        state = prompt.get("state")
        documents = prompt.get("documents", {})

        if state == "DOCUMENT_CHECK":
            pending = documents.get("unextracted") or []
            if pending:
                return {
                    "tool": "extract_document",
                    "arguments": {"document_id": pending[0]},
                    "reasoning": "read the document that has arrived",
                }
            missing = documents.get("missing") or []
            if missing:
                return {
                    "tool": "request_information",
                    "arguments": {
                        "document_type": missing[0],
                        "reason": "this document is required and has not been provided",
                    },
                    "reasoning": "ask the applicant for what is missing",
                }
            return {
                "tool": "check_required_documents",
                "arguments": {},
                "reasoning": "confirm the file is complete",
            }

        if state == "INCOME_VERIFICATION":
            return {
                "tool": "verify_income",
                "arguments": {},
                "reasoning": "compare stated income against the payslip",
            }

        return {"tool": "get_application", "arguments": {}, "reasoning": "review the application"}
