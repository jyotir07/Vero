"""The extract_document tool.

Where a failed extraction has to become a recorded, recoverable workflow outcome rather
than an exception that loses the application.
"""

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.db.models import Application, Document, WorkflowRun
from vero.document_ai.base import ExtractionFailed
from vero.document_ai.fake import FIXTURE_MARKER, FakeDocumentExtractor
from vero.domain.enums import ApplicationState, DocumentStatus, DocumentType
from vero.domain.money import rupees_to_paise
from vero.storage import LocalDiskStorage
from vero.tools import documents
from vero.tools.executor import ToolContext


def _fixture_bytes(payload: dict[str, object]) -> bytes:
    return b"%PDF-1.4 synthetic\n" + FIXTURE_MARKER + json.dumps(payload).encode() + b"\n"


@pytest.fixture
def context(session: Session, tmp_path: Path) -> ToolContext:
    app = Application(
        applicant_name="Asha Iyer",
        applicant_email="asha@example.invalid",
        gross_monthly_income=rupees_to_paise(Decimal("150000")),
        monthly_debt=rupees_to_paise(Decimal("35000")),
        requested_amount=rupees_to_paise(Decimal("800000")),
        tenure_months=60,
    )
    session.add(app)
    session.flush()
    run = WorkflowRun(application_id=app.id, current_state=ApplicationState.DOCUMENT_CHECK)
    session.add(run)
    session.flush()
    return ToolContext(
        session=session,
        run=run,
        application=app,
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
    )


def _upload(context: ToolContext, doc_type: DocumentType, payload: dict[str, object]) -> Document:
    content = _fixture_bytes(payload)
    uri = context.storage.put(
        application_id=context.application.id, document_type=doc_type, content=content
    )
    document = Document(
        application_id=context.application.id,
        document_type=doc_type,
        storage_uri=uri,
        content_hash=context.storage.content_hash(content),
    )
    context.session.add(document)
    context.session.flush()
    return document


def test_extraction_stores_the_structured_data(context: ToolContext) -> None:
    document = _upload(
        context,
        DocumentType.PAY_SLIP,
        {"document_type": "PAY_SLIP", "monthly_income_paise": 15000000, "employer": "Acme"},
    )
    result = documents.extract_document(context, {"document_id": str(document.id)})

    assert result["status"] == "EXTRACTED"
    assert document.status is DocumentStatus.EXTRACTED
    assert document.extracted_data["monthly_income_paise"] == 15000000
    assert document.extraction_confidence == Decimal("0.950")


def test_extraction_reports_low_confidence_for_the_policy_gate(
    context: ToolContext,
) -> None:
    document = _upload(
        context,
        DocumentType.PAY_SLIP,
        {"document_type": "PAY_SLIP", "monthly_income_paise": 1, "confidence": "0.400"},
    )
    result = documents.extract_document(context, {"document_id": str(document.id)})
    assert result["confidence"] == "0.400"


def test_a_failed_extraction_marks_the_document_and_raises(
    context: ToolContext,
) -> None:
    """The row must record the failure, so a retry knows what already went wrong."""
    document = _upload(
        context, DocumentType.PAY_SLIP, {"document_type": "PAY_SLIP", "fail": True}
    )
    with pytest.raises(ExtractionFailed):
        documents.extract_document(context, {"document_id": str(document.id)})
    assert document.status is DocumentStatus.EXTRACTION_FAILED


def test_a_failed_extraction_leaves_no_half_written_data(context: ToolContext) -> None:
    document = _upload(
        context, DocumentType.PAY_SLIP, {"document_type": "PAY_SLIP", "fail": True}
    )
    with pytest.raises(ExtractionFailed):
        documents.extract_document(context, {"document_id": str(document.id)})
    assert document.extracted_data is None
    assert document.extraction_confidence is None


def test_extracting_an_unknown_document_is_an_error(context: ToolContext) -> None:
    with pytest.raises(documents.DocumentNotInApplication):
        documents.extract_document(context, {"document_id": str(uuid.uuid4())})


def test_a_document_belonging_to_another_application_is_refused(
    session: Session, context: ToolContext
) -> None:
    """Document ids come from model output, so ownership is checked, not assumed."""
    other = Application(
        applicant_name="Ravi Menon",
        applicant_email="ravi@example.invalid",
        gross_monthly_income=rupees_to_paise(Decimal("90000")),
        monthly_debt=rupees_to_paise(Decimal("10000")),
        requested_amount=rupees_to_paise(Decimal("300000")),
        tenure_months=36,
    )
    session.add(other)
    session.flush()
    foreign = Document(
        application_id=other.id,
        document_type=DocumentType.PAY_SLIP,
        storage_uri="local://x/y.bin",
        content_hash="f" * 64,
    )
    session.add(foreign)
    session.flush()

    with pytest.raises(documents.DocumentNotInApplication):
        documents.extract_document(context, {"document_id": str(foreign.id)})


def test_re_extracting_an_already_extracted_document_is_a_no_op(
    context: ToolContext,
) -> None:
    document = _upload(
        context,
        DocumentType.PAY_SLIP,
        {"document_type": "PAY_SLIP", "monthly_income_paise": 15000000},
    )
    documents.extract_document(context, {"document_id": str(document.id)})
    result = documents.extract_document(context, {"document_id": str(document.id)})
    assert result["already_extracted"] is True


def test_every_uploaded_document_can_be_extracted(context: ToolContext) -> None:
    payloads = {
        DocumentType.PAY_SLIP: {"monthly_income_paise": 15000000},
        DocumentType.BANK_STATEMENT: {"closing_balance_paise": 42000000},
        DocumentType.ID_PROOF: {"name": "Asha Iyer"},
    }
    for doc_type, extra in payloads.items():
        document = _upload(context, doc_type, {"document_type": doc_type.value, **extra})
        documents.extract_document(context, {"document_id": str(document.id)})

    stored = context.session.scalars(select(Document)).all()
    assert all(d.status is DocumentStatus.EXTRACTED for d in stored)
