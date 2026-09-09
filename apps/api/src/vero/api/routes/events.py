"""The workflow timeline.

The audit trail as the reviewer sees it: append-only, ordered, and traceable back to a
single application and run.
"""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from vero.api.deps import SessionDep, load_application
from vero.db.models import WorkflowEvent
from vero.domain.schemas import WorkflowEventRead

router = APIRouter(prefix="/applications", tags=["events"])


@router.get("/{application_id}/events", response_model=list[WorkflowEventRead])
def list_events(application_id: uuid.UUID, session: SessionDep) -> list[WorkflowEvent]:
    load_application(session, application_id)
    return list(
        session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.application_id == application_id)
            .order_by(WorkflowEvent.seq)
        ).all()
    )
