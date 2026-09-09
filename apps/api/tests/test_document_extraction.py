"""Document extraction behind a swappable interface.

The fake is the default everywhere except a real demo run. It has to fail the same way
the real extractor fails, or the DOCUMENT_CHECK -> FAILED path would only ever be
exercised by the implementation that is hardest to test.
"""

import json
from decimal import Decimal

import pytest

from vero.document_ai.base import ExtractionFailed
from vero.document_ai.fake import FIXTURE_MARKER, FakeDocumentExtractor
from vero.domain.enums import DocumentType


def _fixture(payload: dict[str, object]) -> bytes:
    return b"%PDF-1.4 synthetic\n" + FIXTURE_MARKER + json.dumps(payload).encode() + b"\n"


def test_a_payslip_yields_its_stated_income() -> None:
    content = _fixture(
        {"document_type": "PAY_SLIP", "monthly_income_paise": 15000000, "employer": "Acme"}
    )
    result = FakeDocumentExtractor().extract(
        document_type=DocumentType.PAY_SLIP, content=content
    )
    assert result.data["monthly_income_paise"] == 15000000
    assert result.data["employer"] == "Acme"


def test_confidence_defaults_high_but_is_reported() -> None:
    content = _fixture({"document_type": "PAY_SLIP", "monthly_income_paise": 1})
    result = FakeDocumentExtractor().extract(
        document_type=DocumentType.PAY_SLIP, content=content
    )
    assert result.confidence == Decimal("0.950")


def test_a_fixture_may_declare_low_confidence() -> None:
    """Low confidence is what routes a case to a human, so it must be expressible."""
    content = _fixture(
        {"document_type": "PAY_SLIP", "monthly_income_paise": 1, "confidence": "0.400"}
    )
    result = FakeDocumentExtractor().extract(
        document_type=DocumentType.PAY_SLIP, content=content
    )
    assert result.confidence == Decimal("0.400")


def test_an_unreadable_document_fails_extraction() -> None:
    """No marker: the extractor cannot make anything of the bytes."""
    with pytest.raises(ExtractionFailed):
        FakeDocumentExtractor().extract(
            document_type=DocumentType.PAY_SLIP, content=b"not a document"
        )


def test_malformed_fixture_data_fails_rather_than_returning_nonsense() -> None:
    content = b"%PDF\n" + FIXTURE_MARKER + b"{not json}\n"
    with pytest.raises(ExtractionFailed):
        FakeDocumentExtractor().extract(
            document_type=DocumentType.PAY_SLIP, content=content
        )


def test_a_document_of_the_wrong_kind_is_rejected() -> None:
    """Uploading a payslip as an ID proof is a real mistake, not a silent success."""
    content = _fixture({"document_type": "PAY_SLIP", "monthly_income_paise": 1})
    with pytest.raises(ExtractionFailed):
        FakeDocumentExtractor().extract(
            document_type=DocumentType.ID_PROOF, content=content
        )


def test_a_fixture_can_be_told_to_fail_on_purpose() -> None:
    """So the FAILED path can be demonstrated without corrupting a file by hand."""
    content = _fixture({"document_type": "PAY_SLIP", "fail": True})
    with pytest.raises(ExtractionFailed):
        FakeDocumentExtractor().extract(
            document_type=DocumentType.PAY_SLIP, content=content
        )


def test_a_bank_statement_yields_balances() -> None:
    content = _fixture(
        {
            "document_type": "BANK_STATEMENT",
            "closing_balance_paise": 42000000,
            "average_monthly_credit_paise": 15000000,
        }
    )
    result = FakeDocumentExtractor().extract(
        document_type=DocumentType.BANK_STATEMENT, content=content
    )
    assert result.data["closing_balance_paise"] == 42000000


def test_extraction_is_deterministic() -> None:
    """Same bytes, same answer - otherwise the test suite cannot assert on outcomes."""
    content = _fixture({"document_type": "ID_PROOF", "name": "Asha Iyer"})
    extractor = FakeDocumentExtractor()
    first = extractor.extract(document_type=DocumentType.ID_PROOF, content=content)
    second = extractor.extract(document_type=DocumentType.ID_PROOF, content=content)
    assert first == second
