"""Deterministic extractor for tests, CI, and local development.

Synthetic documents carry their own structured answer in a marker line, which this
reads back. That keeps extraction deterministic without pretending it always works: a
document with no marker, a corrupt marker, or the wrong document type all fail exactly
as the real extractor would, and a fixture can ask to fail on purpose so the FAILED
path is reachable without hand-corrupting a file.
"""

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from vero.document_ai.base import (
    DEFAULT_CONFIDENCE,
    ExtractionFailed,
    ExtractionResult,
)
from vero.domain.enums import DocumentType

FIXTURE_MARKER = b"VERO-FIXTURE:"

REQUIRED_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.PAY_SLIP: ("monthly_income_paise",),
    DocumentType.BANK_STATEMENT: ("closing_balance_paise",),
    DocumentType.ID_PROOF: ("name",),
}


class FakeDocumentExtractor:
    def extract(self, *, document_type: DocumentType, content: bytes) -> ExtractionResult:
        payload = self._read_marker(content)

        declared = payload.get("document_type")
        if declared != document_type.value:
            raise ExtractionFailed(
                f"document is a {declared}, not a {document_type.value}"
            )

        if payload.get("fail"):
            raise ExtractionFailed("fixture requested an extraction failure")

        missing = [f for f in REQUIRED_FIELDS[document_type] if f not in payload]
        if missing:
            raise ExtractionFailed(f"missing fields for {document_type.value}: {missing}")

        return ExtractionResult(
            data={k: v for k, v in payload.items() if k not in {"confidence", "fail"}},
            confidence=self._confidence(payload),
        )

    @staticmethod
    def _read_marker(content: bytes) -> dict[str, Any]:
        start = content.find(FIXTURE_MARKER)
        if start == -1:
            raise ExtractionFailed("no readable content in document")
        tail = content[start + len(FIXTURE_MARKER) :]

        # raw_decode stops at the end of the first JSON value rather than requiring the
        # rest of the line to be JSON. In a real PDF the marker sits inside a text
        # operator, so it is followed by ") Tj T* ET" and other page syntax.
        try:
            payload, _ = json.JSONDecoder().raw_decode(
                tail.decode("utf-8", errors="replace").lstrip()
            )
        except json.JSONDecodeError as exc:
            raise ExtractionFailed(f"document data is not readable: {exc}") from exc
        if not isinstance(payload, dict):
            raise ExtractionFailed("document data is not an object")
        return payload

    @staticmethod
    def _confidence(payload: dict[str, Any]) -> Decimal:
        raw = payload.get("confidence")
        if raw is None:
            return DEFAULT_CONFIDENCE
        try:
            return Decimal(str(raw)).quantize(Decimal("0.001"))
        except InvalidOperation as exc:
            raise ExtractionFailed(f"confidence is not a number: {raw!r}") from exc
