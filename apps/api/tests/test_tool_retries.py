"""Bounded retries around tool execution.

docs/plan.md and 02-agent-workflow describe CREDIT_ANALYSIS -> FAILED as reached when
the bureau call is "retries exhausted", and spec section 12 requires retries to be
bounded and observable. Until now there were none: the first failure went straight to
FAILED, so the documents promised reliability the code did not have.

Not everything is worth retrying. A document that is not readable will not become
readable, and a tool the agent may not call will not become permitted. Retrying those
burns time and, where a model is involved, money. Only failures that plausibly go away
on their own are retried.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from vero.db.models import Application, ToolCall, WorkflowRun
from vero.document_ai.base import ExtractionFailed
from vero.document_ai.fake import FakeDocumentExtractor
from vero.domain.enums import Actor, ApplicationState, ToolCallStatus
from vero.domain.money import rupees_to_paise
from vero.events.recorder import EventRecorder
from vero.storage import LocalDiskStorage
from vero.tools.executor import ToolExecutionFailed, ToolExecutor


@pytest.fixture
def run(session: Session) -> WorkflowRun:
    application = Application(
        applicant_name="Asha Iyer",
        applicant_email="asha@example.com",
        gross_monthly_income=rupees_to_paise(Decimal("150000")),
        monthly_debt=rupees_to_paise(Decimal("35000")),
        requested_amount=rupees_to_paise(Decimal("800000")),
        tenure_months=60,
    )
    session.add(application)
    session.flush()
    workflow_run = WorkflowRun(
        application_id=application.id, current_state=ApplicationState.CREDIT_ANALYSIS
    )
    session.add(workflow_run)
    session.flush()
    return workflow_run


def _executor(session: Session, tmp_path: Path, **handlers: Any) -> ToolExecutor:
    return ToolExecutor(
        session=session,
        recorder=EventRecorder(session),
        handlers=handlers,
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
    )


class Flaky:
    """Fails a given number of times, then succeeds."""

    def __init__(self, failures: int, error: Exception) -> None:
        self.remaining = failures
        self.error = error
        self.calls = 0

    def __call__(self, context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        return {"credit_score": 742}


def _transient() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("server closed the connection"))


def test_a_transient_failure_is_retried_and_succeeds(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = Flaky(failures=1, error=_transient())
    result = _executor(session, tmp_path, run_credit_check=handler).execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
    )
    assert handler.calls == 2
    assert result.value == {"credit_score": 742}


def test_retries_are_bounded(session: Session, run: WorkflowRun, tmp_path: Path) -> None:
    """Otherwise a permanently broken dependency is retried until something else breaks."""
    handler = Flaky(failures=99, error=_transient())
    executor = _executor(session, tmp_path, run_credit_check=handler)
    with pytest.raises(ToolExecutionFailed):
        executor.execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM,
        )
    assert handler.calls == 3


def test_the_attempt_budget_is_configurable(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = Flaky(failures=99, error=_transient())
    executor = ToolExecutor(
        session=session,
        recorder=EventRecorder(session),
        handlers={"run_credit_check": handler},
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
        max_attempts=5,
    )
    with pytest.raises(ToolExecutionFailed):
        executor.execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
        )
    assert handler.calls == 5


def test_every_attempt_is_recorded(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """Spec section 12 asks for retries to be observable, not merely bounded."""
    handler = Flaky(failures=2, error=_transient())
    _executor(session, tmp_path, run_credit_check=handler).execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
    )
    calls = session.scalars(select(ToolCall).order_by(ToolCall.attempt)).all()
    assert [c.attempt for c in calls] == [1, 2, 3]
    assert [c.status for c in calls] == [
        ToolCallStatus.ERROR,
        ToolCallStatus.ERROR,
        ToolCallStatus.OK,
    ]


def test_an_unreadable_document_is_not_retried(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """It will not become readable, so a retry only wastes the budget."""

    def unreadable(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        raise ExtractionFailed("no readable content in document")

    handler_calls = {"n": 0}

    def counting(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        handler_calls["n"] += 1
        return unreadable(context, arguments)

    with pytest.raises(ToolExecutionFailed):
        _executor(session, tmp_path, run_credit_check=counting).execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
        )
    assert handler_calls["n"] == 1


def test_a_programming_error_is_not_retried(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """An unrecognised failure may have left a side effect behind; do not repeat it."""
    calls = {"n": 0}

    def broken(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        raise KeyError("required_argument")

    with pytest.raises(ToolExecutionFailed):
        _executor(session, tmp_path, run_credit_check=broken).execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
        )
    assert calls["n"] == 1


def test_a_statement_timeout_is_recorded_as_a_timeout(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """TIMEOUT was an unreachable enum value until the database could produce one."""
    from psycopg.errors import QueryCanceled

    def slow(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        raise OperationalError("SELECT pg_sleep(60)", {}, QueryCanceled("canceled"))

    with pytest.raises(ToolExecutionFailed):
        _executor(session, tmp_path, run_credit_check=slow).execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
        )

    statuses = {c.status for c in session.scalars(select(ToolCall)).all()}
    assert statuses == {ToolCallStatus.TIMEOUT}


def test_a_successful_first_attempt_records_one_call(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = Flaky(failures=0, error=_transient())
    _executor(session, tmp_path, run_credit_check=handler).execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
    )
    calls = session.scalars(select(ToolCall)).all()
    assert len(calls) == 1
    assert calls[0].attempt == 1


def test_a_retry_survives_a_genuinely_aborted_transaction(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """A real database error aborts the transaction, not just the statement.

    Without a savepoint per attempt, the retry would run on a session Postgres has
    already put into a failed state and every subsequent statement would fail. The
    synthetic OperationalError used elsewhere in this file cannot show that, because
    raising it in Python leaves the transaction perfectly healthy.
    """
    from sqlalchemy import text

    attempts = {"n": 0}

    def times_out_once(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            context.session.execute(text("SET LOCAL statement_timeout = '100ms'"))
            context.session.execute(text("SELECT pg_sleep(1)"))
        # Prove the session is usable again rather than merely not raising.
        assert context.session.execute(text("SELECT 1")).scalar() == 1
        return {"credit_score": 742}

    result = _executor(session, tmp_path, run_credit_check=times_out_once).execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.SYSTEM
    )

    assert attempts["n"] == 2
    assert result.value == {"credit_score": 742}
    statuses = [c.status for c in session.scalars(select(ToolCall).order_by(ToolCall.attempt))]
    assert statuses == [ToolCallStatus.TIMEOUT, ToolCallStatus.OK]
