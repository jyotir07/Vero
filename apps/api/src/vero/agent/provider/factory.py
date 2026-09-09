"""Chooses an LLM provider from configuration.

Defaults to the scripted fake, so a fresh checkout runs its whole test suite with no API
key and no network. Reaching the real model is a deliberate act.
"""

from vero.agent.provider.base import LLMProvider
from vero.agent.provider.fake import OfflineAgentProvider
from vero.config import Settings


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        # A rule-based stand-in, not a language model. The default configuration has to
        # produce a working demo without an API key, and an empty script would fail the
        # first agent step of every run.
        return OfflineAgentProvider()

    if not settings.openai_api_key:
        raise ValueError("LLM_PROVIDER=openai requires OPENAI_API_KEY")

    from openai import OpenAI

    from vero.agent.provider.openai_provider import OpenAIProvider

    return OpenAIProvider(
        client=OpenAI(api_key=settings.openai_api_key),
        model=settings.openai_model,
        timeout=settings.llm_timeout_seconds,
    )
