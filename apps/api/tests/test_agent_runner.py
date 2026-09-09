"""The agent loop.

What matters here is not that the happy path works, but that every way the model can
misbehave ends in a recorded, bounded, non-corrupting outcome: bad output is repaired
then given up on, a forbidden tool is refused and logged, a timeout fails the run
cleanly, and a model that never converges hits a step ceiling instead of spinning.
"""

import json
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.agent.provider.base import LLMTimeout
from vero.agent.provider.fake import ProgrammableLLMProvider
from vero.agent.runner import AgentRunner
from vero.db.models import (
    AgentAction,
    Application,
    Document,
    HumanReview,
    RiskAssessment,
    WorkflowEvent,
    WorkflowRun,
)
from vero.document_ai.fake import FIXTURE_MARKER, FakeDocumentExtractor
from vero.domain.enums import (
    ApplicationState,
    DocumentStatus,
    DocumentType,
    EventType,
    ValidationResult,
    WorkflowStatus,
)
from vero.domain.money import rupees_to_paise
from vero.storage import LocalDiskStorage


def _fixture_bytes(payload: dict[str, object]) -> bytes:
    return b"%PDF-1.4 synthetic\n" + FIXTURE_MARKER + json.dumps(payload).encode() + b"\n"


def _propose(tool: str, **arguments: object) -> str:
    return json.dumps({"tool": tool, "arguments": arguments, "reasoning": "because"})


class Scenario:
    """Builds an application, its documents, and a runner wired to a fake model."""

    def __init__(self, session: Session, tmp_path: Path) -> None:
        self.session = session
        self.storage = LocalDiskStorage(root=tmp_path / "store")
        self.extractor = FakeDocumentExtractor()
        self.application: Application
        self.run: WorkflowRun

    def build(
        self,
        *,
        tenure_months: int = 60,
        credit_score: int = 742,
        income_paise: int = 15_000_000,
        documents: dict[DocumentType, dict[str, object]] | None = None,
    ) -> "Scenario":
        self.application = Application(
            applicant_name="Asha Iyer",
            applicant_email="asha@example.com",
            gross_monthly_income=rupees_to_paise(Decimal("150000")),
            monthly_debt=rupees_to_paise(Decimal("35000")),
            requested_amount=rupees_to_paise(Decimal("800000")),
            tenure_months=tenure_months,
            synthetic_credit_score=credit_score,
        )
        self.session.add(self.application)
        self.session.flush()

        payloads = (
            documents
            if documents is not None
            else {
                DocumentType.PAY_SLIP: {"monthly_income_paise": income_paise},
                DocumentType.BANK_STATEMENT: {"closing_balance_paise": 42_000_000},
                DocumentType.ID_PROOF: {"name": "Asha Iyer"},
            }
        )
        for doc_type, extra in payloads.items():
            content = _fixture_bytes({"document_type": doc_type.value, **extra})
            uri = self.storage.put(
                application_id=self.application.id, document_type=doc_type, content=content
            )
            self.session.add(
                Document(
                    application_id=self.application.id,
                    document_type=doc_type,
                    storage_uri=uri,
                    content_hash=self.storage.content_hash(content),
                )
            )

        self.run = WorkflowRun(application_id=self.application.id)
        self.session.add(self.run)
        self.session.flush()
        return self

    def cooperative_responder(self) -> "ProgrammableLLMProvider":
        """A model that does the sensible thing for whatever state it is shown."""

        def respond(system: str, user: str) -> str:
            payload = json.loads(user)
            state = payload["state"]
            if state == ApplicationState.DOCUMENT_CHECK.value:
                pending = payload["documents"]["unextracted"]
                if pending:
                    return _propose("extract_document", document_id=pending[0])
                if payload["documents"]["missing"]:
                    return _propose(
                        "request_information",
                        document_type=payload["documents"]["missing"][0],
                        reason="required document is missing",
                    )
                return _propose("check_required_documents")
            if state == ApplicationState.INCOME_VERIFICATION.value:
                return _propose("verify_income")
            return _propose("get_application")

        return ProgrammableLLMProvider(respond)

    def runner(self, provider: object, **kwargs: object) -> AgentRunner:
        return AgentRunner(
            session=self.session,
            provider=provider,  # type: ignore[arg-type]
            storage=self.storage,
            extractor=self.extractor,
            **kwargs,  # type: ignore[arg-type]
        )


@pytest.fixture
def scenario(session: Session, tmp_path: Path) -> Scenario:
    return Scenario(session, tmp_path)


def test_a_clean_application_is_approved(scenario: Scenario) -> None:
    s = scenario.build(tenure_months=60)
    s.runner(s.cooperative_responder()).run(s.run)
    assert s.run.current_state is ApplicationState.APPROVED
    assert s.run.status is WorkflowStatus.COMPLETED


def test_the_same_applicant_over_36_months_goes_to_a_human(scenario: Scenario) -> None:
    """Calibration from docs/plan.md, now reached through the whole workflow."""
    s = scenario.build(tenure_months=36)
    s.runner(s.cooperative_responder()).run(s.run)
    assert s.run.current_state is ApplicationState.HUMAN_REVIEW
    review = s.session.scalars(select(HumanReview)).one()
    assert review.triggered_gates == ["DTI"]


def test_a_failing_gate_is_rejected_without_human_review(scenario: Scenario) -> None:
    s = scenario.build(credit_score=600)
    s.runner(s.cooperative_responder()).run(s.run)
    assert s.run.current_state is ApplicationState.REJECTED
    assert s.session.scalars(select(HumanReview)).all() == []


def test_a_missing_document_pauses_for_the_applicant(scenario: Scenario) -> None:
    s = scenario.build(
        documents={
            DocumentType.PAY_SLIP: {"monthly_income_paise": 15_000_000},
            DocumentType.ID_PROOF: {"name": "Asha Iyer"},
        }
    )
    s.runner(s.cooperative_responder()).run(s.run)
    assert s.run.current_state is ApplicationState.MORE_INFORMATION_REQUIRED
    assert s.run.status is WorkflowStatus.PAUSED


def test_an_unreadable_document_fails_the_workflow(scenario: Scenario) -> None:
    s = scenario.build(
        documents={
            DocumentType.PAY_SLIP: {"fail": True},
            DocumentType.BANK_STATEMENT: {"closing_balance_paise": 1},
            DocumentType.ID_PROOF: {"name": "Asha Iyer"},
        }
    )
    s.runner(s.cooperative_responder()).run(s.run)
    assert s.run.current_state is ApplicationState.FAILED


def test_malformed_output_is_repaired_and_the_run_continues(scenario: Scenario) -> None:
    """One bad answer should cost a retry, not the application."""
    s = scenario.build()
    state = {"broken": 0}
    cooperative = s.cooperative_responder()

    def respond(system: str, user: str) -> str:
        if state["broken"] < 1:
            state["broken"] += 1
            return "I think we should probably approve this one"
        return cooperative._responder(system, user)

    s.runner(ProgrammableLLMProvider(respond)).run(s.run)
    assert s.run.current_state is ApplicationState.APPROVED

    rejected = s.session.scalars(
        select(AgentAction).where(AgentAction.validation_result == ValidationResult.REJECTED_SCHEMA)
    ).all()
    assert len(rejected) == 1


def test_output_that_never_becomes_valid_fails_the_run(scenario: Scenario) -> None:
    s = scenario.build()
    s.runner(ProgrammableLLMProvider(lambda system, user: "nonsense")).run(s.run)
    assert s.run.current_state is ApplicationState.FAILED
    assert s.run.status is WorkflowStatus.FAILED


def test_repair_attempts_are_bounded(scenario: Scenario) -> None:
    """Otherwise a model that always answers badly costs an unbounded number of calls."""
    s = scenario.build()
    provider = ProgrammableLLMProvider(lambda system, user: "nonsense")
    s.runner(provider, max_repairs=2).run(s.run)
    assert len(provider.calls) == 3


def test_a_forbidden_tool_is_recorded_as_a_permission_refusal(scenario: Scenario) -> None:
    """The thesis, visible in the audit trail rather than only in a unit test."""
    s = scenario.build()
    cooperative = s.cooperative_responder()
    state = {"tried": False}

    def respond(system: str, user: str) -> str:
        if not state["tried"]:
            state["tried"] = True
            return _propose("update_application_status", to_state="APPROVED")
        return cooperative._responder(system, user)

    s.runner(ProgrammableLLMProvider(respond)).run(s.run)

    refusal = s.session.scalars(
        select(AgentAction).where(
            AgentAction.validation_result == ValidationResult.REJECTED_PERMISSION
        )
    ).one()
    assert refusal.proposed_action["tool"] == "update_application_status"
    assert s.run.current_state is ApplicationState.APPROVED


def test_a_model_timeout_fails_the_run_without_corrupting_it(scenario: Scenario) -> None:
    s = scenario.build()

    def respond(system: str, user: str) -> Exception:
        return LLMTimeout("model took too long")

    s.runner(ProgrammableLLMProvider(respond)).run(s.run)
    assert s.run.current_state is ApplicationState.FAILED
    # The transition chain must still be intact and end where the run ended.
    events = s.session.scalars(
        select(WorkflowEvent)
        .where(WorkflowEvent.event_type == EventType.STATE_CHANGED)
        .order_by(WorkflowEvent.seq)
    ).all()
    assert events[-1].to_state is ApplicationState.FAILED


def test_a_model_that_never_converges_hits_the_step_ceiling(scenario: Scenario) -> None:
    """A cooperative-looking but useless model must not loop forever."""
    s = scenario.build()
    provider = ProgrammableLLMProvider(lambda system, user: _propose("get_application"))
    s.runner(provider, max_steps=6).run(s.run)
    assert s.run.current_state is ApplicationState.FAILED


def test_every_proposal_is_recorded_with_its_cost(scenario: Scenario) -> None:
    """Phase 3 needs a real latency and token baseline, not an estimate."""
    s = scenario.build()
    s.runner(s.cooperative_responder()).run(s.run)
    actions = s.session.scalars(select(AgentAction)).all()
    assert actions
    assert all(a.model == "fake" for a in actions)
    assert all(a.prompt_tokens is not None for a in actions)
    assert all(a.latency_ms is not None for a in actions)


def test_the_transition_chain_is_unbroken(scenario: Scenario) -> None:
    s = scenario.build()
    s.runner(s.cooperative_responder()).run(s.run)
    events = s.session.scalars(
        select(WorkflowEvent)
        .where(WorkflowEvent.event_type == EventType.STATE_CHANGED)
        .order_by(WorkflowEvent.seq)
    ).all()
    chain = [(e.from_state, e.to_state) for e in events]
    for (_, previous_to), (next_from, _) in pairwise(chain):
        assert previous_to == next_from
    assert chain[0][0] is ApplicationState.RECEIVED


def test_the_assessment_that_decided_the_case_is_persisted(scenario: Scenario) -> None:
    s = scenario.build()
    s.runner(s.cooperative_responder()).run(s.run)
    assessment = s.session.scalars(select(RiskAssessment)).one()
    assert assessment.credit_score == 742
    assert assessment.dti_proposed == Decimal("0.357431")


def test_everything_on_file_is_extracted_before_pausing(scenario: Scenario) -> None:
    """Two documents can be waiting at once, and both should be dealt with.

    Pausing after the first would waste a request cycle and leave the application
    looking incomplete while it sits with the applicant.
    """
    s = scenario.build(
        documents={
            DocumentType.PAY_SLIP: {"monthly_income_paise": 15_000_000},
            DocumentType.ID_PROOF: {"name": "Asha Iyer"},
        }
    )
    s.runner(s.cooperative_responder()).run(s.run)

    assert s.run.current_state is ApplicationState.MORE_INFORMATION_REQUIRED
    stored = s.session.scalars(select(Document)).all()
    assert [d.status for d in stored] == [DocumentStatus.EXTRACTED] * 2
    assert s.run.document_request_count == 1
