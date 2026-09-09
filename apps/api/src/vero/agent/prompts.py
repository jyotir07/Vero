"""What the model is told.

The user message is JSON rather than prose: it is assembled from the database, it is
what gets replayed when a run is debugged, and a structured payload keeps the prompt
small enough that the token cost of a step stays roughly flat as an application grows.
"""

import json
from typing import Any

from sqlalchemy import select

from vero.db.models import Document, WorkflowRun
from vero.domain.enums import DocumentStatus, DocumentType
from vero.tools.registry import tools_available_to_agent

SYSTEM_PROMPT = """You are the underwriting agent for Vero, a simulated credit system.

You do not make decisions and you do not move applications between states. You choose
one tool to call next, and the backend decides what that means.

Reply with a single JSON object and nothing else:
{"tool": "<tool name>", "arguments": {...}, "reasoning": "<one sentence>"}

Only the tools listed as available may be used. Anything else is refused."""


def build_user_prompt(
    *, run: WorkflowRun, session: Any, feedback: str | None = None
) -> str:
    documents = session.scalars(
        select(Document).where(Document.application_id == run.application_id)
    ).all()
    present = {d.document_type for d in documents}

    payload: dict[str, Any] = {
        "state": run.current_state.value,
        "available_tools": sorted(tools_available_to_agent(run.current_state)),
        "application": {
            "gross_monthly_income_paise": int(run.application.gross_monthly_income),
            "monthly_debt_paise": int(run.application.monthly_debt),
            "requested_amount_paise": int(run.application.requested_amount),
            "tenure_months": run.application.tenure_months,
        },
        "documents": {
            "missing": sorted(t.value for t in set(DocumentType) - present),
            "unextracted": [
                str(d.id) for d in documents if d.status is DocumentStatus.UPLOADED
            ],
            "failed": [
                str(d.id)
                for d in documents
                if d.status is DocumentStatus.EXTRACTION_FAILED
            ],
        },
        "requests_made": run.document_request_count,
    }
    if feedback:
        # Fed back verbatim so the model can correct the specific thing that was wrong.
        payload["previous_attempt_rejected"] = feedback
    return json.dumps(payload)
