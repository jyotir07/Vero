"""Workflow tools: reading the application, moving it, and escalating it."""

from typing import Any

from sqlalchemy import select

from vero.db.models import Document, HumanReview, RiskAssessment
from vero.domain.enums import Actor, ApplicationState, DocumentType
from vero.policy.decision import evaluate_application
from vero.state_machine.machine import apply_transition
from vero.tools.credit import run_credit_check
from vero.tools.executor import ToolContext
from vero.tools.finance import verify_income

REQUIRED_DOCUMENTS = frozenset(DocumentType)


def get_application(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """What the agent is allowed to know.

    synthetic_credit_score is withheld on purpose: the agent asks the bureau tool for a
    score rather than reading the seed that decides the answer.
    """
    app = context.application
    return {
        "id": str(app.id),
        "applicant_name": app.applicant_name,
        "applicant_email": app.applicant_email,
        "gross_monthly_income_paise": int(app.gross_monthly_income),
        "monthly_debt_paise": int(app.monthly_debt),
        "requested_amount_paise": int(app.requested_amount),
        "tenure_months": app.tenure_months,
        "annual_rate_bps": app.annual_rate_bps,
        "state": context.run.current_state.value,
        "documents_on_file": sorted(
            d.document_type.value
            for d in context.session.scalars(
                select(Document).where(Document.application_id == app.id)
            ).all()
        ),
    }


def check_required_documents(
    context: ToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    present = {
        d.document_type
        for d in context.session.scalars(
            select(Document).where(Document.application_id == context.application.id)
        ).all()
    }
    missing = REQUIRED_DOCUMENTS - present
    return {
        "missing": sorted(m.value for m in missing),
        "present": sorted(p.value for p in present),
        "complete": not missing,
    }


def request_information(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Tell the applicant what is missing.

    This notifies; it does not bound the loop. The runner counts round trips when it
    pauses, because a cycle is one exchange with the applicant rather than one tool
    call, and the agent may reasonably call this more than once in a turn.
    """
    return {
        "document_type": arguments["document_type"],
        "reason": arguments.get("reason", ""),
        "requests_made": context.run.document_request_count,
    }


def create_human_review(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    review = HumanReview(
        application_id=context.application.id,
        workflow_run_id=context.run.id,
        reason=arguments["reason"],
        triggered_gates=list(arguments.get("triggered_gates", [])),
    )
    context.session.add(review)
    context.session.flush()
    return {"review_id": str(review.id), "status": review.status.value}


def evaluate_policy(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic gates and persist what they decided.

    The score and verified income are looked up rather than accepted from the caller
    when absent, so a proposal cannot smuggle in favourable numbers.
    """
    app = context.application
    score = arguments.get("credit_score")
    if score is None:
        score = run_credit_check(context, {})["credit_score"]
    verified = verify_income(context, {})["verified_monthly_income_paise"]

    evaluation = evaluate_application(
        credit_score=int(score),
        gross_monthly_income=app.gross_monthly_income,
        verified_monthly_income=verified,
        monthly_debt=app.monthly_debt,
        principal=app.requested_amount,
        months=app.tenure_months,
        annual_rate_bps=app.annual_rate_bps,
    )

    context.session.add(
        RiskAssessment(
            application_id=app.id,
            workflow_run_id=context.run.id,
            credit_score=int(score),
            emi=int(evaluation.emi),
            disposable_income=int(evaluation.disposable_income),
            dti_current=evaluation.dti_current,
            dti_proposed=evaluation.dti_proposed,
            lti=evaluation.lti,
            income_divergence=evaluation.income_divergence,
            gate_bands={g.gate.value: g.band.value for g in evaluation.gates},
            overall=evaluation.overall,
            outcome=evaluation.outcome,
        )
    )
    context.session.flush()

    return {
        "outcome": evaluation.outcome.value,
        "overall": evaluation.overall.value,
        "tripped_gates": [g.value for g in evaluation.tripped_gates],
        "gate_bands": {g.gate.value: g.band.value for g in evaluation.gates},
        "emi_paise": int(evaluation.emi),
        "dti_proposed": str(evaluation.dti_proposed),
    }


def update_application_status(
    context: ToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Move the run. System-only, and still checked against the transition table.

    Being the system tool does not make it a back door: an illegal move is refused here
    exactly as it would be anywhere else.
    """
    target = ApplicationState(arguments["to_state"])
    source = context.run.current_state
    context.run.current_state = apply_transition(source, target, actor=Actor.SYSTEM)
    context.session.flush()
    return {"from": source.value, "to": target.value}
