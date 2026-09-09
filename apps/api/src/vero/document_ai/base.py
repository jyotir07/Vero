"""The document extraction contract.

Two implementations sit behind this: OpenAI vision for a real run, and a deterministic
fake everywhere else. The fake is not a stub that always succeeds - it fails on
unreadable input, on the wrong document type, and on demand, because DOCUMENT_CHECK ->
FAILED is a path the workflow has to survive and therefore a path the tests must reach.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from vero.domain.enums import DocumentType

DEFAULT_CONFIDENCE = Decimal("0.950")


class ExtractionFailed(Exception):
    """The document could not be turned into structured data."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExtractionResult:
    data: dict[str, Any]
    confidence: Decimal


class DocumentExtractor(Protocol):
    def extract(
        self, *, document_type: DocumentType, content: bytes
    ) -> ExtractionResult: ...
