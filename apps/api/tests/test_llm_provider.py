"""The LLM provider seam.

The fake is what every test and CI run uses, so it has to be able to reproduce the
failures that matter: a timeout, and output the validator will refuse.
"""

import pytest

from vero.agent.provider.base import LLMTimeout
from vero.agent.provider.fake import FakeLLMProvider, ScriptExhausted


def test_scripted_responses_are_returned_in_order() -> None:
    provider = FakeLLMProvider(["first", "second"])
    assert provider.complete(system="s", user="u").content == "first"
    assert provider.complete(system="s", user="u").content == "second"


def test_a_response_reports_the_model_and_token_usage() -> None:
    """These land on agent_action, which is where Phase 3 gets its latency baseline."""
    response = FakeLLMProvider(["x"]).complete(system="s", user="u")
    assert response.model == "fake"
    assert response.prompt_tokens is not None
    assert response.latency_ms >= 0


def test_the_script_can_raise_a_timeout() -> None:
    provider = FakeLLMProvider([LLMTimeout("took too long")])
    with pytest.raises(LLMTimeout):
        provider.complete(system="s", user="u")


def test_running_off_the_end_of_the_script_is_loud() -> None:
    """Silently repeating the last answer would let a runaway loop look like success."""
    provider = FakeLLMProvider(["only one"])
    provider.complete(system="s", user="u")
    with pytest.raises(ScriptExhausted):
        provider.complete(system="s", user="u")


def test_prompts_are_recorded_for_inspection() -> None:
    provider = FakeLLMProvider(["x"])
    provider.complete(system="the rules", user="the case")
    assert provider.calls == [("the rules", "the case")]
