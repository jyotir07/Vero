"""The generated fixtures must be readable by the extractor that will read them.

Generating PDFs and writing an extractor separately is exactly how you end up with two
components that each work and do not fit together.
"""

import json
from pathlib import Path

import pytest

from vero.document_ai.base import ExtractionFailed
from vero.document_ai.fake import FakeDocumentExtractor
from vero.domain.enums import DocumentType

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "documents"

FILENAMES = {
    DocumentType.PAY_SLIP: "payslip.pdf",
    DocumentType.BANK_STATEMENT: "bank-statement.pdf",
    DocumentType.ID_PROOF: "id-proof.pdf",
}


def _applicants() -> list[dict[str, object]]:
    index = FIXTURE_ROOT / "index.json"
    if not index.exists():
        pytest.skip("fixtures not generated; run scripts/generate_fixtures.py")
    return json.loads(index.read_text())


def test_fixtures_have_been_generated() -> None:
    assert _applicants(), "no fixture applicants found"


@pytest.mark.parametrize("doc_type", list(DocumentType))
def test_every_generated_document_can_be_extracted(doc_type: DocumentType) -> None:
    extractor = FakeDocumentExtractor()
    for applicant in _applicants():
        path = FIXTURE_ROOT / str(applicant["slug"]) / FILENAMES[doc_type]
        content = path.read_bytes()

        if applicant.get("fail") and doc_type is DocumentType.PAY_SLIP:
            with pytest.raises(ExtractionFailed):
                extractor.extract(document_type=doc_type, content=content)
            continue

        result = extractor.extract(document_type=doc_type, content=content)
        assert result.data


def test_the_payslip_reports_the_income_the_page_shows() -> None:
    """What extraction returns has to match what a reviewer would read on screen."""
    extractor = FakeDocumentExtractor()
    for applicant in _applicants():
        if applicant.get("fail"):
            continue
        content = (FIXTURE_ROOT / str(applicant["slug"]) / "payslip.pdf").read_bytes()
        result = extractor.extract(document_type=DocumentType.PAY_SLIP, content=content)
        assert result.data["monthly_income_paise"] == applicant["monthly_income_paise"]


def test_the_low_confidence_fixture_actually_reports_low_confidence() -> None:
    extractor = FakeDocumentExtractor()
    doubtful = [a for a in _applicants() if a.get("confidence")]
    assert doubtful, "no low-confidence fixture to exercise the confidence gate"
    for applicant in doubtful:
        content = (FIXTURE_ROOT / str(applicant["slug"]) / "payslip.pdf").read_bytes()
        result = extractor.extract(document_type=DocumentType.PAY_SLIP, content=content)
        assert str(result.confidence) == applicant["confidence"]
