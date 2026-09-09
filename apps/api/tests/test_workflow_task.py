"""The background task that runs the workflow outside a request.

These cover what the API tests structurally cannot. TestClient runs background tasks
synchronously, so in that world an upload is always fully processed before the next
arrives and the interesting orderings never happen.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.agent.provider.fake import OfflineAgentProvider
from vero.api.workflow_task import advance_workflow
from vero.db.models import Application, Document, WorkflowRun
from vero.document_ai.fake import FIXTURE_MARKER, FakeDocumentExtractor
from vero.domain.enums import ApplicationState, DocumentType, WorkflowStatus
from vero.domain.money import rupees_to_paise
from vero.storage import LocalDiskStorage


def _pdf(payload: dict[str, object]) -> bytes:
    return b"%PDF-1.4 synthetic\n" + FIXTURE_MARKER + json.dumps(payload).encode() + b"\n"


@pytest.fixture
def scope(session: Session):  # type: ignore[no-untyped-def]
    @contextmanager
    def _scope() -> Iterator[Session]:
        yield session

    return _scope


def _seed(
    session: Session, storage: LocalDiskStorage, *, state: ApplicationState, documents: dict
) -> Application:
    application = Application(
        applicant_name="Asha Iyer",
        applicant_email="asha@example.com",
        gross_monthly_income=rupees_to_paise(Decimal("150000")),
        monthly_debt=rupees_to_paise(Decimal("35000")),
        requested_amount=rupees_to_paise(Decimal("800000")),
        tenure_months=60,
        synthetic_credit_score=742,
    )
    session.add(application)
    session.flush()
    for doc_type, extra in documents.items():
        content = _pdf({"document_type": doc_type.value, **extra})
        uri = storage.put(
            application_id=application.id, document_type=doc_type, content=content
        )
        session.add(
            Document(
                application_id=application.id,
                document_type=doc_type,
                storage_uri=uri,
                content_hash=storage.content_hash(content),
            )
        )
    session.add(
        WorkflowRun(
            application_id=application.id,
            current_state=state,
            status=WorkflowStatus.PAUSED
            if state is ApplicationState.MORE_INFORMATION_REQUIRED
            else WorkflowStatus.RUNNING,
            document_request_count=1,
        )
    )
    session.flush()
    return application


ALL_DOCS = {
    DocumentType.PAY_SLIP: {"monthly_income_paise": 15_000_000},
    DocumentType.BANK_STATEMENT: {"closing_balance_paise": 42_000_000},
    DocumentType.ID_PROOF: {"name": "Asha Iyer"},
}


def test_a_waiting_application_resumes_when_the_task_runs(
    session: Session, tmp_path: Path, scope  # type: ignore[no-untyped-def]
) -> None:
    """The resume decision belongs at execution time, not request time.

    An upload that arrives while an earlier task is still working sees a run that is not
    yet paused, so a request-time check would skip the resume. Its own task then finds
    the run paused and, without this, would return having done nothing - stranding an
    application that has every document it needs.
    """
    storage = LocalDiskStorage(root=tmp_path / "store")
    application = _seed(
        session, storage, state=ApplicationState.MORE_INFORMATION_REQUIRED, documents=ALL_DOCS
    )

    advance_workflow(
        application_id=application.id,
        scope=scope,
        provider=OfflineAgentProvider(),
        storage=storage,
        extractor=FakeDocumentExtractor(),
        resume_after_documents=True,
    )

    run = session.scalars(
        select(WorkflowRun).where(WorkflowRun.application_id == application.id)
    ).one()
    assert run.current_state is ApplicationState.APPROVED


def test_a_task_not_triggered_by_an_upload_leaves_a_waiting_run_alone(
    session: Session, tmp_path: Path, scope  # type: ignore[no-untyped-def]
) -> None:
    """Only a document arriving should take an application off the applicant's desk."""
    storage = LocalDiskStorage(root=tmp_path / "store")
    application = _seed(
        session, storage, state=ApplicationState.MORE_INFORMATION_REQUIRED, documents=ALL_DOCS
    )

    advance_workflow(
        application_id=application.id,
        scope=scope,
        provider=OfflineAgentProvider(),
        storage=storage,
        extractor=FakeDocumentExtractor(),
    )

    run = session.scalars(
        select(WorkflowRun).where(WorkflowRun.application_id == application.id)
    ).one()
    assert run.current_state is ApplicationState.MORE_INFORMATION_REQUIRED


def test_a_missing_run_is_reported_not_crashed(
    session: Session, tmp_path: Path, scope  # type: ignore[no-untyped-def]
) -> None:
    import uuid

    advance_workflow(
        application_id=uuid.uuid4(),
        scope=scope,
        provider=OfflineAgentProvider(),
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
    )
