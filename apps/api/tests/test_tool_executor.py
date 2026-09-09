"""Tool execution, recording, and idempotent replay.

Every side effect in the system goes through here, so this is where retries have to stop
being dangerous. A replayed step returns what was recorded rather than running again.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vero.db.models import Application, ToolCall, WorkflowRun
from vero.document_ai.fake import FakeDocumentExtractor
from vero.domain.enums import Actor, ApplicationState, ToolCallStatus
from vero.domain.money import rupees_to_paise
from vero.events.recorder import EventRecorder
from vero.storage import LocalDiskStorage
from vero.tools.executor import ToolExecutionFailed, ToolExecutor
from vero.tools.registry import ToolNotPermittedError


@pytest.fixture
def run(session: Session) -> WorkflowRun:
    app = Application(
        applicant_name="Asha Iyer",
        applicant_email="asha@example.com",
        gross_monthly_income=rupees_to_paise(Decimal("150000")),
        monthly_debt=rupees_to_paise(Decimal("35000")),
        requested_amount=rupees_to_paise(Decimal("800000")),
        tenure_months=60,
    )
    session.add(app)
    session.flush()
    workflow_run = WorkflowRun(
        application_id=app.id, current_state=ApplicationState.CREDIT_ANALYSIS
    )
    session.add(workflow_run)
    session.flush()
    return workflow_run


class CountingHandler:
    """Counts invocations, so 'did not run again' is provable rather than assumed."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.result = result if result is not None else {"ok": True}

    def __call__(self, context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self.result


def _executor(session: Session, tmp_path: Path, **handlers: Any) -> ToolExecutor:
    return ToolExecutor(
        session=session,
        recorder=EventRecorder(session),
        handlers=handlers,
        storage=LocalDiskStorage(root=tmp_path / "store"),
        extractor=FakeDocumentExtractor(),
    )


def test_executing_a_tool_returns_its_result(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = CountingHandler({"dti": "0.357431"})
    result = _executor(session, tmp_path, calculate_dti=handler).execute(
        run=run, tool_name="calculate_dti", arguments={}, actor=Actor.AGENT
    )
    assert result.value == {"dti": "0.357431"}
    assert result.replayed is False


def test_executing_a_tool_records_the_call(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    _executor(session, tmp_path, calculate_dti=CountingHandler()).execute(
        run=run, tool_name="calculate_dti", arguments={"a": 1}, actor=Actor.AGENT
    )
    call = session.scalars(select(ToolCall)).one()
    assert call.tool_name == "calculate_dti"
    assert call.status is ToolCallStatus.OK
    assert call.arguments == {"a": 1}


def test_replaying_a_step_does_not_run_the_tool_again(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """The whole point of the idempotency key: a retry must not double a side effect."""
    handler = CountingHandler({"score": 742})
    executor = _executor(session, tmp_path, run_credit_check=handler)

    first = executor.execute(
        run=run, tool_name="run_credit_check", arguments={"pan": "X"}, actor=Actor.AGENT
    )
    second = executor.execute(
        run=run, tool_name="run_credit_check", arguments={"pan": "X"}, actor=Actor.AGENT
    )

    assert handler.calls == 1
    assert second.replayed is True
    assert second.value == first.value


def test_a_replay_does_not_write_a_second_call_row(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    executor = _executor(session, tmp_path, run_credit_check=CountingHandler())
    for _ in range(3):
        executor.execute(
            run=run, tool_name="run_credit_check", arguments={"pan": "X"}, actor=Actor.AGENT
        )
    assert session.scalar(select(func.count()).select_from(ToolCall)) == 1


def test_different_arguments_are_a_different_step(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = CountingHandler()
    executor = _executor(session, tmp_path, run_credit_check=handler)
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={"pan": "X"}, actor=Actor.AGENT
    )
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={"pan": "Y"}, actor=Actor.AGENT
    )
    assert handler.calls == 2


def test_argument_order_does_not_change_the_key(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """Same arguments in a different order are the same call, not a new one."""
    handler = CountingHandler()
    executor = _executor(session, tmp_path, run_credit_check=handler)
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={"a": 1, "b": 2}, actor=Actor.AGENT
    )
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={"b": 2, "a": 1}, actor=Actor.AGENT
    )
    assert handler.calls == 1


def test_a_later_step_may_call_the_same_tool_again(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = CountingHandler()
    executor = _executor(session, tmp_path, run_credit_check=handler)
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
    )
    run.step_seq += 1
    executor.execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
    )
    assert handler.calls == 2


def test_a_tool_outside_its_state_is_refused_before_it_runs(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = CountingHandler()
    with pytest.raises(ToolNotPermittedError):
        _executor(session, tmp_path, extract_document=handler).execute(
            run=run, tool_name="extract_document", arguments={}, actor=Actor.AGENT
        )
    assert handler.calls == 0


def test_the_agent_cannot_execute_a_system_only_tool(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    handler = CountingHandler()
    with pytest.raises(ToolNotPermittedError):
        _executor(session, tmp_path, update_application_status=handler).execute(
            run=run, tool_name="update_application_status", arguments={}, actor=Actor.AGENT
        )
    assert handler.calls == 0


def test_the_system_may_execute_a_system_only_tool(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """Permission is about the agent; the workflow itself still needs the tool."""
    handler = CountingHandler()
    result = _executor(session, tmp_path, update_application_status=handler).execute(
        run=run, tool_name="update_application_status", arguments={}, actor=Actor.SYSTEM
    )
    assert handler.calls == 1
    assert result.replayed is False


def test_a_failing_tool_is_recorded_rather_than_swallowed(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    def explode(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("bureau unreachable")

    with pytest.raises(ToolExecutionFailed):
        _executor(session, tmp_path, run_credit_check=explode).execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
        )

    call = session.scalars(select(ToolCall)).one()
    assert call.status is ToolCallStatus.ERROR
    assert "bureau unreachable" in (call.error or "")


def test_a_failed_call_is_not_replayed_as_a_success(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """A retry after a failure must actually retry, not return the failure as a result."""
    attempts = {"n": 0}

    def flaky(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient")
        return {"score": 742}

    executor = _executor(session, tmp_path, run_credit_check=flaky)
    with pytest.raises(ToolExecutionFailed):
        executor.execute(
            run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
        )
    result = executor.execute(
        run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
    )
    assert result.value == {"score": 742}
    assert attempts["n"] == 2


def test_a_failed_attempt_keeps_the_real_key_for_its_step(
    session: Session, run: WorkflowRun, tmp_path: Path
) -> None:
    """Attempts on one step should be queryable together, so the key must not be mangled.

    Uniqueness applies only to successful calls: one step may fail repeatedly and
    succeed once, and all those rows describe the same step.
    """
    attempts = {"n": 0}

    def flaky(context: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return {"score": 742}

    executor = _executor(session, tmp_path, run_credit_check=flaky)
    for _ in range(2):
        with pytest.raises(ToolExecutionFailed):
            executor.execute(
                run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT
            )
    executor.execute(run=run, tool_name="run_credit_check", arguments={}, actor=Actor.AGENT)

    keys = session.scalars(select(ToolCall.idempotency_key)).all()
    assert len(set(keys)) == 1, f"attempts on one step drifted apart: {set(keys)}"
    statuses = sorted(s.value for s in session.scalars(select(ToolCall.status)).all())
    assert statuses == ["ERROR", "ERROR", "OK"]
