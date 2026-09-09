"""Which extractor configuration selects."""

import pytest

from vero.config import Settings
from vero.document_ai.factory import build_extractor
from vero.document_ai.fake import FakeDocumentExtractor


def test_the_fake_is_the_default() -> None:
    """No API key, no network: the default has to work on a fresh checkout."""
    assert isinstance(build_extractor(Settings()), FakeDocumentExtractor)


def test_selecting_openai_without_a_key_fails_loudly() -> None:
    """Better a startup error than silently extracting nothing during a demo."""
    settings = Settings(document_extractor="openai", openai_api_key="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_extractor(settings)


def test_the_offline_provider_is_the_default() -> None:
    """The default configuration must produce a working demo, not a broken one."""
    from vero.agent.provider.factory import build_provider
    from vero.agent.provider.fake import OfflineAgentProvider

    assert isinstance(build_provider(Settings()), OfflineAgentProvider)


def test_the_offline_provider_drives_document_check() -> None:
    import json

    from vero.agent.provider.fake import OfflineAgentProvider

    prompt = json.dumps(
        {"state": "DOCUMENT_CHECK", "documents": {"unextracted": ["abc"], "missing": []}}
    )
    answer = json.loads(OfflineAgentProvider().complete(system="s", user=prompt).content)
    assert answer["tool"] == "extract_document"
    assert answer["arguments"]["document_id"] == "abc"


def test_selecting_openai_llm_without_a_key_fails_loudly() -> None:
    from vero.agent.provider.factory import build_provider

    settings = Settings(llm_provider="openai", openai_api_key="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_provider(settings)
