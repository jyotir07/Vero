"""Runs the workflow outside the request.

Phase 1 executes the agent in-process as a FastAPI background task. The state that
matters lives in Postgres from the first commit, so the swap to a queue and workers in
Phase 2 replaces this file and nothing else.

Two things here exist because tasks and requests genuinely race, which a TestClient
never shows: the run row is locked for the duration, so two tasks cannot interleave
state changes on one application; and the decision to resume a paused application is
made here, at execution time, rather than by the request that scheduled the task. A
request-time check misses whenever an upload arrives while an earlier task is still
working, and the application is then stranded with every document present and nothing
left to wake it.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.agent.provider.base import LLMProvider
from vero.agent.runner import AgentRunner
from vero.db.models import WorkflowRun
from vero.document_ai.base import DocumentExtractor
from vero.domain.enums import Actor, ApplicationState, EventType, WorkflowStatus
from vero.events.recorder import EventRecorder
from vero.state_machine.machine import apply_transition
from vero.storage import DocumentStorage

logger = logging.getLogger(__name__)


def advance_workflow(
    *,
    application_id: uuid.UUID,
    scope: Callable[[], AbstractContextManager[Session]],
    provider: LLMProvider,
    storage: DocumentStorage,
    extractor: DocumentExtractor,
    resume_after_documents: bool = False,
) -> None:
    with scope() as session:
        run = session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.application_id == application_id)
            .with_for_update()
        ).one_or_none()
        if run is None:
            logger.warning("no workflow run for application %s", application_id)
            return

        waiting = run.current_state is ApplicationState.MORE_INFORMATION_REQUIRED
        if resume_after_documents and waiting:
            _resume(session, run)

        runner = AgentRunner(
            session=session, provider=provider, storage=storage, extractor=extractor
        )
        # The runner records its own failures as workflow events and moves the run to
        # FAILED. Anything escaping it is a bug in Vero, not a bad application, so it is
        # logged rather than silently swallowed.
        try:
            runner.run(run)
        except Exception:
            logger.exception("workflow crashed for application %s", application_id)
            raise


def _resume(session: Session, run: WorkflowRun) -> None:
    """Take the application back to document check after the applicant supplied something.

    Attributed to the applicant because they caused it; the transition table owns that
    edge and would refuse any other actor.
    """
    source = run.current_state
    run.current_state = apply_transition(
        source, ApplicationState.DOCUMENT_CHECK, actor=Actor.APPLICANT
    )
    run.status = WorkflowStatus.RUNNING
    EventRecorder(session).record(
        run=run,
        event_type=EventType.STATE_CHANGED,
        actor=Actor.APPLICANT,
        from_state=source,
        to_state=ApplicationState.DOCUMENT_CHECK,
    )
    session.flush()
