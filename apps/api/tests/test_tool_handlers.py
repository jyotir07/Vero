"""The tools themselves.

These are thin: the arithmetic already lives in vero.policy and is tested there. What
matters here is that each tool reads the right state, writes only through the models,
and returns something the agent can reason about.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.db.models import Application, Document, HumanReview, RiskAssessment, WorkflowRun
from vero.document_ai.fake import FakeDocumentExtractor
from vero.domain.enums import ApplicationState, DocumentStatus, DocumentType
from vero.domain.money import rupees_to_paise
from vero.storage import LocalDiskStorage
from vero.tools import credit, finance, workflow
from vero.tools.executor import ToolContext


@pytest.fixture
def context(session: Session, tmp_path: Path) -> ToolContext:
    app = Application(
        applicant_name="Asha Iyer",
        applicant_email="asha@example.invalid",
        gross_monthly_income=rupees_to_paise(Decimal("150000")),
        monthly_debt=rupees_to_paise(Decimal("35000")),
        requested_amount=rupees_to_paise(Decimal("800000")),
        tenure_months=60,
        synthetic_credit_score=742,
    )
    session.add(app)
    session.flush()
    run = WorkflowRun(application_id=app.id, current_state=ApplicationState.CREDIT_ANALYSIS)
    session.add(run)
    session.flush()
    return ToolContext(
        session=session,
        run=run,
        application=app,
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
    )


def test_get_application_returns_the_figures_the_agent_reasons_about(
    context: ToolContext,
) -> None:
    result = workflow.get_application(context, {})
    assert result["applicant_name"] == "Asha Iyer"
    assert result["tenure_months"] == 60
    assert result["state"] == "CREDIT_ANALYSIS"


def test_get_application_does_not_leak_the_bureau_seed(context: ToolContext) -> None:
    """The agent asks the bureau for a score; it does not get to read the answer key."""
    assert "synthetic_credit_score" not in workflow.get_application(context, {})


def test_calculate_dti_reports_both_ratios(context: ToolContext) -> None:
    result = finance.calculate_dti(context, {})
    assert result["dti_current"] == "0.233333"
    assert result["dti_proposed"] == "0.357431"


def test_calculate_affordability_reports_the_instalment_and_headroom(
    context: ToolContext,
) -> None:
    result = finance.calculate_affordability(context, {})
    assert result["emi_paise"] == 1861460
    assert result["disposable_income_paise"] == 9638540


def test_run_credit_check_returns_the_seeded_score(context: ToolContext) -> None:
    assert credit.run_credit_check(context, {})["credit_score"] == 742


def test_run_credit_check_is_deterministic_without_a_seed(
    session: Session, context: ToolContext
) -> None:
    """An unseeded applicant still gets a stable score, so reruns reproduce."""
    context.application.synthetic_credit_score = None
    session.flush()
    first = credit.run_credit_check(context, {})["credit_score"]
    second = credit.run_credit_check(context, {})["credit_score"]
    assert first == second
    assert 300 <= first <= 900


def test_verify_income_falls_back_to_stated_income_without_documents(
    context: ToolContext,
) -> None:
    result = finance.verify_income(context, {})
    assert result["verified_monthly_income_paise"] == context.application.gross_monthly_income
    assert result["source"] == "STATED"


def test_verify_income_prefers_an_extracted_payslip(
    session: Session, context: ToolContext
) -> None:
    session.add(
        Document(
            application_id=context.application.id,
            document_type=DocumentType.PAY_SLIP,
            storage_uri="file://payslip.pdf",
            content_hash="a" * 64,
            status=DocumentStatus.EXTRACTED,
            extracted_data={"monthly_income_paise": 13000000},
            extraction_confidence=Decimal("0.950"),
        )
    )
    session.flush()
    result = finance.verify_income(context, {})
    assert result["verified_monthly_income_paise"] == 13000000
    assert result["source"] == "PAY_SLIP"
    assert result["divergence"] == "0.133333"


def test_check_required_documents_lists_what_is_missing(context: ToolContext) -> None:
    result = workflow.check_required_documents(context, {})
    assert set(result["missing"]) == {"PAY_SLIP", "BANK_STATEMENT", "ID_PROOF"}
    assert result["complete"] is False


def test_check_required_documents_is_satisfied_when_all_are_present(
    session: Session, context: ToolContext
) -> None:
    for i, doc_type in enumerate(DocumentType):
        session.add(
            Document(
                application_id=context.application.id,
                document_type=doc_type,
                storage_uri=f"file://{doc_type}.pdf",
                content_hash=str(i) * 64,
                status=DocumentStatus.EXTRACTED,
            )
        )
    session.flush()
    result = workflow.check_required_documents(context, {})
    assert result["missing"] == []
    assert result["complete"] is True


def test_request_information_counts_against_the_loop_bound(
    session: Session, context: ToolContext
) -> None:
    """The bound is what stops MORE_INFORMATION_REQUIRED cycling forever."""
    before = context.run.document_request_count
    workflow.request_information(
        context, {"document_type": "BANK_STATEMENT", "reason": "missing"}
    )
    assert context.run.document_request_count == before + 1


def test_create_human_review_records_why_the_case_escalated(
    session: Session, context: ToolContext
) -> None:
    workflow.create_human_review(
        context, {"reason": "DTI in review band", "triggered_gates": ["DTI"]}
    )
    review = session.scalars(select(HumanReview)).one()
    assert review.reason == "DTI in review band"
    assert review.triggered_gates == ["DTI"]


def test_evaluate_policy_persists_the_assessment_it_decided_on(
    session: Session, context: ToolContext
) -> None:
    result = workflow.evaluate_policy(context, {"credit_score": 742})
    assert result["outcome"] == "APPROVE"

    assessment = session.scalars(select(RiskAssessment)).one()
    assert assessment.credit_score == 742
    assert assessment.dti_proposed == Decimal("0.357431")
    assert assessment.gate_bands["DTI"] == "PASS"


def test_evaluate_policy_refers_the_same_applicant_over_a_shorter_tenure(
    session: Session, context: ToolContext
) -> None:
    context.application.tenure_months = 36
    session.flush()
    result = workflow.evaluate_policy(context, {"credit_score": 742})
    assert result["outcome"] == "REFER"
    assert result["tripped_gates"] == ["DTI"]


def test_update_application_status_moves_the_run(
    session: Session, context: ToolContext
) -> None:
    workflow.update_application_status(context, {"to_state": "RISK_ASSESSMENT"})
    assert context.run.current_state is ApplicationState.RISK_ASSESSMENT


def test_update_application_status_refuses_an_illegal_move(context: ToolContext) -> None:
    """Even the system tool goes through the transition table."""
    from vero.state_machine.machine import IllegalTransitionError

    with pytest.raises(IllegalTransitionError):
        workflow.update_application_status(context, {"to_state": "APPROVED"})
