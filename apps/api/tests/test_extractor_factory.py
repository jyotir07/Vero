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
