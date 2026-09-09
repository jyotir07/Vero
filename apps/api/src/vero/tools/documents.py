"""Document tools.

extract_document is the one place where a model-supplied identifier is used to reach a
stored file, so ownership is checked rather than trusted: a document id that belongs to
another application is refused, not fetched.
"""

import uuid
from typing import Any

from vero.db.models import Document
from vero.document_ai.base import ExtractionFailed
from vero.domain.enums import DocumentStatus
from vero.tools.executor import ToolContext
from vero.tools.registry import ToolError


class DocumentNotInApplication(ToolError):
    def __init__(self, document_id: str) -> None:
        super().__init__(f"no document {document_id} on this application")
        self.document_id = document_id


def _load(context: ToolContext, document_id: str) -> Document:
    try:
        parsed = uuid.UUID(document_id)
    except ValueError:
        raise DocumentNotInApplication(document_id) from None

    document = context.session.get(Document, parsed)
    if document is None or document.application_id != context.application.id:
        raise DocumentNotInApplication(document_id)
    return document


def extract_document(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    document = _load(context, str(arguments["document_id"]))

    if document.status is DocumentStatus.EXTRACTED:
        return {
            "document_id": str(document.id),
            "document_type": document.document_type.value,
            "status": document.status.value,
            "already_extracted": True,
            "confidence": (
                str(document.extraction_confidence)
                if document.extraction_confidence is not None
                else None
            ),
        }

    content = context.storage.get(document.storage_uri)
    try:
        result = context.extractor.extract(
            document_type=document.document_type, content=content
        )
    except ExtractionFailed:
        # Record the failure on the row and leave the data columns untouched, so a
        # partially written extraction never looks like a successful one.
        document.status = DocumentStatus.EXTRACTION_FAILED
        context.session.flush()
        raise

    document.extracted_data = result.data
    document.extraction_confidence = result.confidence
    document.status = DocumentStatus.EXTRACTED
    context.session.flush()

    return {
        "document_id": str(document.id),
        "document_type": document.document_type.value,
        "status": document.status.value,
        "already_extracted": False,
        "confidence": str(result.confidence),
        "data": result.data,
    }
