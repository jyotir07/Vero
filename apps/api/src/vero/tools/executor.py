"""Runs tools, records what happened, and refuses to run the same step twice.

Every side effect in the workflow passes through execute(). That makes this the one
place where a retry can be made safe: a step is identified by (run, step, tool,
arguments), and if a successful call already exists under that identity, the recorded
result is returned instead of running the handler again.

Failed calls are deliberately not replayed. A retry after a timeout has to actually
retry, otherwise a transient failure becomes a permanent one.

Retries are bounded and only cover failures that plausibly resolve themselves. A
document that could not be read will not become readable, and an unrecognised error may
have left a side effect behind, so neither is repeated.

Each attempt runs inside a savepoint. A database error aborts the surrounding
transaction, so without one the retry would fail on a session that is already poisoned,
and any partial write from the failed attempt would still be sitting there.
"""

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from psycopg.errors import QueryCanceled
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from vero.db.models import Application, ToolCall, WorkflowRun
from vero.document_ai.base import DocumentExtractor
from vero.domain.enums import Actor, EventType, ToolCallStatus
from vero.events.recorder import EventRecorder
from vero.storage import DocumentStorage
from vero.tools.registry import ToolError, check_tool_permitted, get_tool

# Failures where the dependency may simply be having a moment. Anything else is either
# deterministic or not understood, and repeating it buys nothing.
RETRYABLE = (OperationalError, TimeoutError, ConnectionError)

DEFAULT_MAX_ATTEMPTS = 3


def _classify(exc: BaseException) -> ToolCallStatus:
    if isinstance(exc, TimeoutError):
        return ToolCallStatus.TIMEOUT
    if isinstance(exc, OperationalError) and isinstance(exc.orig, QueryCanceled):
        # statement_timeout or lock_timeout fired.
        return ToolCallStatus.TIMEOUT
    return ToolCallStatus.ERROR


class ToolExecutionFailed(ToolError):
    def __init__(self, tool_name: str, cause: Exception) -> None:
        super().__init__(f"{tool_name} failed: {cause}")
        self.tool_name = tool_name
        self.cause = cause


@dataclass(frozen=True)
class ToolContext:
    session: Session
    run: WorkflowRun
    application: Application
    storage: DocumentStorage
    extractor: DocumentExtractor


@dataclass(frozen=True)
class ToolResult:
    value: dict[str, Any]
    replayed: bool


Handler = Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def idempotency_key(
    *, run_id: Any, step_seq: int, tool_name: str, arguments: Mapping[str, Any]
) -> str:
    """Identity of a step.

    Arguments are canonicalised with sorted keys so that the same call written two ways
    is recognised as one call rather than two.
    """
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    return f"{run_id}:{step_seq}:{tool_name}:{digest}"


class ToolExecutor:
    def __init__(
        self,
        *,
        session: Session,
        recorder: EventRecorder,
        handlers: Mapping[str, Handler],
        storage: DocumentStorage,
        extractor: DocumentExtractor,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._session = session
        self._recorder = recorder
        self._handlers = handlers
        self._storage = storage
        self._extractor = extractor
        self._max_attempts = max_attempts

    def execute(
        self,
        *,
        run: WorkflowRun,
        tool_name: str,
        arguments: dict[str, Any],
        actor: Actor,
        agent_action_id: Any | None = None,
    ) -> ToolResult:
        # Permission first: a refused tool must never reach its handler.
        if actor is Actor.AGENT:
            check_tool_permitted(tool_name, state=run.current_state)
        else:
            get_tool(tool_name)

        key = idempotency_key(
            run_id=run.id,
            step_seq=run.step_seq,
            tool_name=tool_name,
            arguments=arguments,
        )

        recorded = self._session.scalars(
            select(ToolCall).where(
                ToolCall.idempotency_key == key, ToolCall.status == ToolCallStatus.OK
            )
        ).first()
        if recorded is not None:
            return ToolResult(value=recorded.result or {}, replayed=True)

        handler = self._handlers[tool_name]
        context = ToolContext(
            session=self._session,
            run=run,
            application=run.application,
            storage=self._storage,
            extractor=self._extractor,
        )

        self._recorder.record(
            run=run,
            event_type=EventType.TOOL_CALL_STARTED,
            actor=actor,
            payload={"tool": tool_name},
        )

        for attempt in range(1, self._max_attempts + 1):
            started = time.perf_counter()
            try:
                # A savepoint per attempt: a database failure aborts the transaction, and
                # rolling back to here also discards whatever the failed attempt wrote.
                with self._session.begin_nested():
                    value = handler(context, arguments)
            except Exception as exc:
                status = _classify(exc)
                self._record_call(
                    run=run,
                    key=key,
                    tool_name=tool_name,
                    arguments=arguments,
                    result=None,
                    status=status,
                    error=str(exc),
                    started=started,
                    agent_action_id=agent_action_id,
                    attempt=attempt,
                )
                self._recorder.record(
                    run=run,
                    event_type=EventType.TOOL_CALL_FAILED,
                    actor=actor,
                    payload={
                        "tool": tool_name,
                        "error": str(exc),
                        "attempt": attempt,
                        "status": status.value,
                    },
                )
                if attempt >= self._max_attempts or not isinstance(exc, RETRYABLE):
                    raise ToolExecutionFailed(tool_name, exc) from exc
                continue

            self._record_call(
                run=run,
                key=key,
                tool_name=tool_name,
                arguments=arguments,
                result=value,
                status=ToolCallStatus.OK,
                error=None,
                started=started,
                agent_action_id=agent_action_id,
                attempt=attempt,
            )
            self._recorder.record(
                run=run,
                event_type=EventType.TOOL_CALL_SUCCEEDED,
                actor=actor,
                payload={"tool": tool_name, "attempt": attempt},
            )
            return ToolResult(value=value, replayed=False)

        raise AssertionError("unreachable: the loop either returns or raises")

    def _record_call(
        self,
        *,
        run: WorkflowRun,
        key: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | None,
        status: ToolCallStatus,
        error: str | None,
        started: float,
        agent_action_id: Any | None,
        attempt: int,
    ) -> None:
        self._session.add(
            ToolCall(
                workflow_run_id=run.id,
                agent_action_id=agent_action_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
                status=status,
                error=error,
                attempt=attempt,
                idempotency_key=key,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        self._session.flush()
