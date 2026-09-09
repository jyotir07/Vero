"""Appends to the workflow event log.

Sequence numbers are assigned under a row lock on the run. Phase 1 has a single
in-process executor and would survive without it, but the lock is what lets Phase 2 add
workers without revisiting this, and the unique constraint on (workflow_run_id, seq) is
the backstop if it is ever wrong.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vero.db.models import WorkflowEvent, WorkflowRun
from vero.domain.enums import Actor, ApplicationState, EventType


class EventRecorder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        run: WorkflowRun,
        event_type: EventType,
        actor: Actor,
        from_state: ApplicationState | None = None,
        to_state: ApplicationState | None = None,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        self._session.execute(
            select(WorkflowRun.id).where(WorkflowRun.id == run.id).with_for_update()
        )
        last_seq = self._session.scalar(
            select(func.coalesce(func.max(WorkflowEvent.seq), 0)).where(
                WorkflowEvent.workflow_run_id == run.id
            )
        )
        event = WorkflowEvent(
            application_id=run.application_id,
            workflow_run_id=run.id,
            seq=(last_seq or 0) + 1,
            event_type=event_type,
            actor=actor,
            from_state=from_state,
            to_state=to_state,
            payload=payload if payload is not None else {},
        )
        self._session.add(event)
        self._session.flush()
        return event
