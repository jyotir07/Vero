"""Chooses an extractor from configuration.

Defaults to the fake so that tests, CI, and local development need no API key and no
network. Selecting the real one is a deliberate act.
"""

from vero.config import Settings
from vero.document_ai.base import DocumentExtractor
from vero.document_ai.fake import FakeDocumentExtractor


def build_extractor(settings: Settings) -> DocumentExtractor:
    if settings.document_extractor == "fake":
        return FakeDocumentExtractor()

    if not settings.openai_api_key:
        raise ValueError("DOCUMENT_EXTRACTOR=openai requires OPENAI_API_KEY")

    from openai import OpenAI

    from vero.document_ai.openai_vision import OpenAIVisionExtractor

    return OpenAIVisionExtractor(
        client=OpenAI(api_key=settings.openai_api_key),
        model=settings.openai_model,
        timeout=settings.llm_timeout_seconds,
    )
