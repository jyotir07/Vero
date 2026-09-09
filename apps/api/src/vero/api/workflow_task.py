"""Runs the workflow outside the request.

Phase 1 executes the agent in-process as a FastAPI background task. The state that
matters lives in Postgres from the first commit, so the swap to a queue and workers in
Phase 2 replaces this file and nothing else.

The task opens its own session: the request that scheduled it has already returned and
its session is closed.
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
from vero.storage import DocumentStorage

logger = logging.getLogger(__name__)


def advance_workflow(
    *,
    application_id: uuid.UUID,
    scope: Callable[[], AbstractContextManager[Session]],
    provider: LLMProvider,
    storage: DocumentStorage,
    extractor: DocumentExtractor,
) -> None:
    with scope() as session:
        run = session.scalars(
            select(WorkflowRun).where(WorkflowRun.application_id == application_id)
        ).one_or_none()
        if run is None:
            logger.warning("no workflow run for application %s", application_id)
            return

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
