"""Drives an application through the workflow.

The division of labour is the whole point of the project: in DOCUMENT_CHECK and
INCOME_VERIFICATION the model chooses which tool to call next, and everywhere else the
work is deterministic. In no state does the model decide where the application goes -
_next_state does that by reading what the tools actually recorded.

Every loop here is bounded. A model that answers badly gets a fixed number of repairs, a
model that answers plausibly but uselessly hits a step ceiling, and both end in FAILED
rather than in an unbounded spend or a half-finished application.
"""

import time
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from vero.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from vero.agent.provider.base import LLMError, LLMProvider
from vero.agent.validator import validate_proposal
from vero.db.models import AgentAction, Document, WorkflowRun
from vero.document_ai.base import DocumentExtractor
from vero.domain.enums import (
    Actor,
    ApplicationState,
    DocumentStatus,
    DocumentType,
    EventType,
    ValidationResult,
    WorkflowStatus,
)
from vero.events.recorder import EventRecorder
from vero.policy.decision import PolicyOutcome
from vero.policy.rules import MAX_PASS_DIVERGENCE
from vero.state_machine.machine import apply_transition
from vero.state_machine.transitions import TERMINAL_STATES
from vero.storage import DocumentStorage
from vero.tools.executor import Handler, ToolExecutionFailed, ToolExecutor
from vero.tools.handlers import HANDLERS

# States where the model picks the next action. Everywhere else the step is deterministic.
LLM_DRIVEN_STATES = frozenset(
    {ApplicationState.DOCUMENT_CHECK, ApplicationState.INCOME_VERIFICATION}
)

# States where the run stops and waits for someone outside the system.
PAUSE_STATES = frozenset(
    {ApplicationState.HUMAN_REVIEW, ApplicationState.MORE_INFORMATION_REQUIRED}
)

MAX_DOCUMENT_REQUESTS = 3
MIN_EXTRACTION_CONFIDENCE = 0.7


# (target state, who caused the move). Checked against the transition table, so an
# attribution that disagrees with the documented owner surfaces as a bug.
Move = tuple[ApplicationState, Actor]


class AgentStepFailed(Exception):
    """The model could not produce a usable action for this step."""


class AgentRunner:
    def __init__(
        self,
        *,
        session: Session,
        provider: LLMProvider,
        storage: DocumentStorage,
        extractor: DocumentExtractor,
        handlers: Mapping[str, Handler] | None = None,
        max_steps: int = 25,
        max_repairs: int = 2,
    ) -> None:
        self._session = session
        self._provider = provider
        self._recorder = EventRecorder(session)
        self._max_steps = max_steps
        self._max_repairs = max_repairs
        self._executor = ToolExecutor(
            session=session,
            recorder=self._recorder,
            handlers=handlers if handlers is not None else HANDLERS,
            storage=storage,
            extractor=extractor,
        )

    def run(self, run: WorkflowRun) -> WorkflowRun:
        for _ in range(self._max_steps):
            if run.current_state in TERMINAL_STATES:
                return self._settle(run)
            if run.current_state in PAUSE_STATES:
                run.status = WorkflowStatus.PAUSED
                self._session.flush()
                return run

            try:
                self._work(run)
            except (AgentStepFailed, ToolExecutionFailed) as exc:
                self._fail(run, str(exc))
                return self._settle(run)

            decision = self._next_state(run)
            if decision is not None and decision[0] is not run.current_state:
                self._move(run, decision[0], actor=decision[1])

            run.step_seq += 1
            self._session.flush()

        # A model that keeps producing valid but unproductive actions ends here rather
        # than looping until something else runs out.
        self._fail(run, f"step budget of {self._max_steps} exhausted")
        return self._settle(run)

    # -- work -------------------------------------------------------------------

    def _work(self, run: WorkflowRun) -> None:
        if run.current_state in LLM_DRIVEN_STATES:
            self._agent_step(run)
        elif run.current_state is ApplicationState.CREDIT_ANALYSIS:
            self._system_call(run, "run_credit_check")
            self._system_call(run, "calculate_dti")
            self._system_call(run, "calculate_affordability")
        elif run.current_state is ApplicationState.RISK_ASSESSMENT:
            self._system_call(run, "evaluate_policy")
        # RECEIVED and DECISION do no work; _next_state moves them on.

    def _agent_step(self, run: WorkflowRun) -> None:
        feedback: str | None = None

        for _ in range(self._max_repairs + 1):
            prompt = build_user_prompt(run=run, session=self._session, feedback=feedback)
            started = time.perf_counter()
            try:
                response = self._provider.complete(system=SYSTEM_PROMPT, user=prompt)
            except LLMError as exc:
                raise AgentStepFailed(f"model call failed: {exc}") from exc

            validation = validate_proposal(response.content, state=run.current_state)
            action = self._record_action(
                run=run,
                validation_result=validation.result,
                proposed=(
                    validation.action.model_dump()
                    if validation.action
                    else {"raw": response.content[:500]}
                ),
                reason=validation.reason,
                model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

            if validation.result is ValidationResult.ACCEPTED and validation.action:
                self._executor.execute(
                    run=run,
                    tool_name=validation.action.tool,
                    arguments=validation.action.arguments,
                    actor=Actor.AGENT,
                    agent_action_id=action.id,
                )
                return

            self._recorder.record(
                run=run,
                event_type=EventType.AGENT_ACTION_REJECTED,
                actor=Actor.AGENT,
                payload={"result": validation.result.value, "reason": validation.reason},
            )
            feedback = validation.reason

        raise AgentStepFailed("model did not produce a valid action within the repair budget")

    def _system_call(self, run: WorkflowRun, tool_name: str) -> None:
        self._executor.execute(
            run=run, tool_name=tool_name, arguments={}, actor=Actor.SYSTEM
        )

    # -- transitions ------------------------------------------------------------

    def _next_state(self, run: WorkflowRun) -> Move | None:
        """Read what the tools recorded and decide where the application goes.

        Deliberately reads the database rather than the model's opinion: the transition
        follows from facts that were persisted, not from what was proposed.
        """
        state = run.current_state

        if state is ApplicationState.RECEIVED:
            return (ApplicationState.DOCUMENT_CHECK, Actor.SYSTEM)

        if state is ApplicationState.DOCUMENT_CHECK:
            return self._after_document_check(run)

        if state is ApplicationState.INCOME_VERIFICATION:
            return self._after_income_verification(run)

        if state is ApplicationState.CREDIT_ANALYSIS:
            return (ApplicationState.RISK_ASSESSMENT, Actor.SYSTEM)

        if state is ApplicationState.RISK_ASSESSMENT:
            return self._after_risk_assessment(run)

        if state is ApplicationState.DECISION:
            return self._after_decision(run)

        return None

    def _documents(self, run: WorkflowRun) -> list[Document]:
        return list(
            self._session.scalars(
                select(Document).where(Document.application_id == run.application_id)
            ).all()
        )

    def _after_document_check(self, run: WorkflowRun) -> Move | None:
        documents = self._documents(run)
        # An unreadable document is a system determination, not something the agent did.
        if any(d.status is DocumentStatus.EXTRACTION_FAILED for d in documents):
            return (ApplicationState.FAILED, Actor.SYSTEM)

        missing = set(DocumentType) - {d.document_type for d in documents}
        if missing:
            # Only pause once everything on file has been dealt with, otherwise the
            # agent never gets a turn to ask and the cycle count never advances.
            if any(d.status is DocumentStatus.UPLOADED for d in documents):
                return None

            # The runner owns the cycle count rather than the tool: a cycle is one
            # round trip to the applicant, which is what the bound is counting.
            run.document_request_count += 1
            self._session.flush()
            if run.document_request_count > MAX_DOCUMENT_REQUESTS:
                return (ApplicationState.FAILED, Actor.SYSTEM)
            # The agent asked for the document, so the pause is attributed to it.
            return (ApplicationState.MORE_INFORMATION_REQUIRED, Actor.AGENT)

        if all(d.status is DocumentStatus.EXTRACTED for d in documents):
            return (ApplicationState.INCOME_VERIFICATION, Actor.AGENT)
        return None

    def _after_income_verification(self, run: WorkflowRun) -> Move | None:
        from vero.tools.executor import ToolContext
        from vero.tools.finance import verify_income

        context = ToolContext(
            session=self._session,
            run=run,
            application=run.application,
            storage=self._executor._storage,
            extractor=self._executor._extractor,
        )
        result = verify_income(context, {})

        confidence = result.get("confidence")
        if confidence is not None and float(confidence) < MIN_EXTRACTION_CONFIDENCE:
            return (ApplicationState.HUMAN_REVIEW, Actor.SYSTEM)
        if float(result["divergence"]) > float(MAX_PASS_DIVERGENCE):
            return (ApplicationState.HUMAN_REVIEW, Actor.SYSTEM)
        return (ApplicationState.CREDIT_ANALYSIS, Actor.SYSTEM)

    def _after_risk_assessment(self, run: WorkflowRun) -> Move:
        assessment = self._latest_assessment(run)
        if assessment is None:
            return (ApplicationState.RISK_ASSESSMENT, Actor.SYSTEM)
        if assessment.outcome is PolicyOutcome.REFER:
            self._executor.execute(
                run=run,
                tool_name="create_human_review",
                arguments={
                    "reason": f"policy referred: {sorted(assessment.gate_bands)}",
                    "triggered_gates": [
                        gate for gate, band in assessment.gate_bands.items() if band != "PASS"
                    ],
                },
                actor=Actor.SYSTEM,
            )
            return (ApplicationState.HUMAN_REVIEW, Actor.SYSTEM)
        return (ApplicationState.DECISION, Actor.SYSTEM)

    def _after_decision(self, run: WorkflowRun) -> Move:
        assessment = self._latest_assessment(run)
        if assessment is not None and assessment.outcome is PolicyOutcome.REJECT:
            return (ApplicationState.REJECTED, Actor.SYSTEM)
        return (ApplicationState.APPROVED, Actor.SYSTEM)

    def _latest_assessment(self, run: WorkflowRun):  # type: ignore[no-untyped-def]
        from vero.db.models import RiskAssessment

        return self._session.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.workflow_run_id == run.id)
            .order_by(RiskAssessment.created_at.desc())
        ).first()

    # -- bookkeeping ------------------------------------------------------------

    def _move(self, run: WorkflowRun, target: ApplicationState, *, actor: Actor) -> None:
        source = run.current_state
        run.current_state = apply_transition(source, target, actor=actor)
        self._recorder.record(
            run=run,
            event_type=EventType.STATE_CHANGED,
            actor=actor,
            from_state=source,
            to_state=target,
        )
        self._session.flush()

    def _fail(self, run: WorkflowRun, reason: str) -> None:
        if run.current_state not in TERMINAL_STATES:
            self._move(run, ApplicationState.FAILED, actor=Actor.SYSTEM)
        run.status = WorkflowStatus.FAILED
        self._recorder.record(
            run=run,
            event_type=EventType.DECISION_MADE,
            actor=Actor.SYSTEM,
            payload={"outcome": "FAILED", "reason": reason},
        )
        self._session.flush()

    def _settle(self, run: WorkflowRun) -> WorkflowRun:
        if run.status is not WorkflowStatus.FAILED:
            run.status = WorkflowStatus.COMPLETED
        self._session.flush()
        return run

    def _record_action(
        self,
        *,
        run: WorkflowRun,
        validation_result: ValidationResult,
        proposed: dict[str, object],
        reason: str | None,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int,
    ) -> AgentAction:
        action = AgentAction(
            workflow_run_id=run.id,
            step_seq=run.step_seq,
            state_at_proposal=run.current_state,
            proposed_action=proposed,
            validation_result=validation_result,
            rejection_reason=reason,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        self._session.add(action)
        self._session.flush()
        self._recorder.record(
            run=run,
            event_type=EventType.AGENT_ACTION_PROPOSED,
            actor=Actor.AGENT,
            payload={"tool": proposed.get("tool"), "result": validation_result.value},
        )
        return action
