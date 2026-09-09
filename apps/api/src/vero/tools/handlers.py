"""Wires tool names to their implementations.

Kept apart from registry.py so that the registry stays importable as pure permission
metadata, with no dependency on the database or the policy engine.
"""

from vero.tools import credit, finance, workflow
from vero.tools.executor import Handler

# Declared rather than silently absent, so the gap is visible instead of surfacing as a
# KeyError the first time the agent reaches for it. extract_document needs the document
# store and the extractor.
PENDING_TOOLS = {"extract_document"}

HANDLERS: dict[str, Handler] = {
    "get_application": workflow.get_application,
    "check_required_documents": workflow.check_required_documents,
    "request_information": workflow.request_information,
    "create_human_review": workflow.create_human_review,
    "evaluate_policy": workflow.evaluate_policy,
    "update_application_status": workflow.update_application_status,
    "calculate_dti": finance.calculate_dti,
    "calculate_affordability": finance.calculate_affordability,
    "verify_income": finance.verify_income,
    "run_credit_check": credit.run_credit_check,
}
