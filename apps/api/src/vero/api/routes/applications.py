"""Application intake and reads."""

import uuid

from fastapi import APIRouter, BackgroundTasks, status
from sqlalchemy import select

from vero.api.deps import (
    ExtractorDep,
    ProviderDep,
    SessionDep,
    SessionScopeDep,
    StorageDep,
    load_application,
)
from vero.api.workflow_task import advance_workflow
from vero.db.models import Application, Document, RiskAssessment, WorkflowRun
from vero.domain.enums import DocumentType
from vero.domain.schemas import ApplicationCreate, ApplicationRead, ApplicationSummary

router = APIRouter(prefix="/applications", tags=["applications"])


def _to_read(session: SessionDep, application: Application) -> ApplicationRead:
    run = session.scalars(
        select(WorkflowRun).where(WorkflowRun.application_id == application.id)
    ).one()
    documents = list(
        session.scalars(
            select(Document).where(Document.application_id == application.id)
        ).all()
    )
    assessment = session.scalars(
        select(RiskAssessment)
        .where(RiskAssessment.application_id == application.id)
        .order_by(RiskAssessment.created_at.desc())
    ).first()

    present = {d.document_type for d in documents}
    return ApplicationRead(
        id=application.id,
        created_at=application.created_at,
        applicant_name=application.applicant_name,
        applicant_email=application.applicant_email,
        gross_monthly_income_paise=int(application.gross_monthly_income),
        monthly_debt_paise=int(application.monthly_debt),
        requested_amount_paise=int(application.requested_amount),
        tenure_months=application.tenure_months,
        annual_rate_bps=application.annual_rate_bps,
        state=run.current_state,
        status=run.status,
        documents=[d for d in documents],  # type: ignore[misc]
        missing_documents=sorted(set(DocumentType) - present),
        risk_assessment=assessment,  # type: ignore[arg-type]
    )


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    session: SessionDep,
    background: BackgroundTasks,
    scope: SessionScopeDep,
    provider: ProviderDep,
    storage: StorageDep,
    extractor: ExtractorDep,
) -> ApplicationRead:
    """Create an application and start work on it.

    Returns immediately in RECEIVED rather than blocking until the workflow finishes:
    the run makes several model calls, and the caller should not wait on them.
    """
    application = Application(
        applicant_name=payload.applicant_name,
        applicant_email=str(payload.applicant_email),
        gross_monthly_income=payload.gross_monthly_income_paise,
        monthly_debt=payload.monthly_debt_paise,
        requested_amount=payload.requested_amount_paise,
        tenure_months=payload.tenure_months,
        synthetic_credit_score=payload.synthetic_credit_score,
    )
    session.add(application)
    session.flush()
    session.add(WorkflowRun(application_id=application.id))
    session.flush()

    read = _to_read(session, application)
    background.add_task(
        advance_workflow,
        application_id=application.id,
        scope=scope,
        provider=provider,
        storage=storage,
        extractor=extractor,
    )
    return read


@router.get("", response_model=list[ApplicationSummary])
def list_applications(session: SessionDep) -> list[ApplicationSummary]:
    rows = session.execute(
        select(Application, WorkflowRun)
        .join(WorkflowRun, WorkflowRun.application_id == Application.id)
        .order_by(Application.created_at.desc())
    ).all()
    return [
        ApplicationSummary(
            id=application.id,
            created_at=application.created_at,
            applicant_name=application.applicant_name,
            requested_amount_paise=int(application.requested_amount),
            tenure_months=application.tenure_months,
            state=run.current_state,
            status=run.status,
        )
        for application, run in rows
    ]


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application_detail(application_id: uuid.UUID, session: SessionDep) -> ApplicationRead:
    return _to_read(session, load_application(session, application_id))
