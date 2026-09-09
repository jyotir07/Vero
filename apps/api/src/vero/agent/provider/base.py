"""The LLM seam.

Concrete calls are OpenAI, but nothing above this line knows that. Timeouts are a named
failure rather than a provider-specific exception, because the workflow has to react to
one the same way regardless of who is behind the interface.
"""

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Any failure to get a usable answer from the model."""


class LLMTimeout(LLMError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    def complete(self, *, system: str, user: str) -> LLMResponse: ...
