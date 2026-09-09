"""Financial tools.

Thin wrappers over vero.policy. The arithmetic is tested there; these exist so the agent
can ask for a number without being trusted to compute one.
"""

from typing import Any

from sqlalchemy import select

from vero.db.models import Document
from vero.domain.enums import DocumentStatus, DocumentType
from vero.domain.money import Paise
from vero.policy import metrics
from vero.policy.product import monthly_emi
from vero.tools.executor import ToolContext


def _emi(context: ToolContext) -> int:
    app = context.application
    return monthly_emi(
        app.requested_amount, annual_rate_bps=app.annual_rate_bps, months=app.tenure_months
    )


def calculate_dti(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    app = context.application
    return {
        "dti_current": str(
            metrics.debt_to_income(
                monthly_debt=app.monthly_debt, gross_monthly_income=app.gross_monthly_income
            )
        ),
        "dti_proposed": str(
            metrics.debt_to_income(
                monthly_debt=app.monthly_debt,
                gross_monthly_income=app.gross_monthly_income,
                emi=_emi(context),
            )
        ),
    }


def calculate_affordability(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    app = context.application
    emi = _emi(context)
    return {
        "emi_paise": int(emi),
        "disposable_income_paise": int(
            metrics.disposable_income(
                gross_monthly_income=app.gross_monthly_income,
                monthly_debt=app.monthly_debt,
                emi=emi,
            )
        ),
        "loan_to_income": str(
            metrics.loan_to_income(
                principal=app.requested_amount, gross_monthly_income=app.gross_monthly_income
            )
        ),
    }


def verify_income(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Compare stated income against what an extracted payslip says.

    With no payslip on file the stated figure is all there is. That is reported as
    source STATED rather than silently presented as verified, because the policy gate
    for income divergence is only meaningful when something was actually checked.
    """
    app = context.application
    payslip = context.session.scalars(
        select(Document).where(
            Document.application_id == app.id,
            Document.document_type == DocumentType.PAY_SLIP,
            Document.status == DocumentStatus.EXTRACTED,
        )
    ).first()

    extracted = (payslip.extracted_data or {}) if payslip else {}
    verified = extracted.get("monthly_income_paise")
    if verified is None:
        return {
            "verified_monthly_income_paise": int(app.gross_monthly_income),
            "source": "STATED",
            "divergence": "0.000000",
            "confidence": None,
        }

    # Paise() is an assertion about JSONB, which carries no type of its own.
    verified_paise = Paise(int(verified))
    return {
        "verified_monthly_income_paise": int(verified_paise),
        "source": DocumentType.PAY_SLIP.value,
        "divergence": str(
            metrics.income_divergence(stated=app.gross_monthly_income, verified=verified_paise)
        ),
        "confidence": (
            str(payslip.extraction_confidence)
            if payslip and payslip.extraction_confidence is not None
            else None
        ),
    }
