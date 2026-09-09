"""The wire format.

These Pydantic models are the single source of truth for the API contract: FastAPI
publishes them as OpenAPI, and the frontend generates its TypeScript from that. Changing
a field here changes both sides, which is the point.

Money crosses the wire as integer paise, never as a decimal string or a float. The
frontend multiplies by 100 once, at the form, rather than every layer guessing.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from vero.domain.enums import (
    Actor,
    ApplicationState,
    DocumentStatus,
    DocumentType,
    EventType,
    WorkflowStatus,
)
from vero.policy.product import ALLOWED_TENURES_MONTHS, MAX_PRINCIPAL, MIN_PRINCIPAL


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicant_name: str = Field(min_length=1, max_length=200)
    applicant_email: EmailStr

    gross_monthly_income_paise: int = Field(gt=0)
    monthly_debt_paise: int = Field(ge=0)
    requested_amount_paise: int = Field(ge=MIN_PRINCIPAL, le=MAX_PRINCIPAL)
    tenure_months: int

    # Seeds the simulated bureau so a demo can reach a chosen outcome. There is no real
    # credit score anywhere in this system.
    synthetic_credit_score: int | None = Field(default=None, ge=300, le=900)

    @field_validator("tenure_months")
    @classmethod
    def tenure_must_be_offered(cls, value: int) -> int:
        if value not in ALLOWED_TENURES_MONTHS:
            raise ValueError(f"tenure must be one of {ALLOWED_TENURES_MONTHS}")
        return value


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: DocumentType
    status: DocumentStatus
    extraction_confidence: Decimal | None = None
    created_at: datetime


class RiskAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    credit_score: int
    emi: int
    disposable_income: int
    dti_current: Decimal
    dti_proposed: Decimal
    lti: Decimal
    income_divergence: Decimal
    gate_bands: dict[str, str]
    overall: str
    outcome: str


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    applicant_name: str
    applicant_email: str

    gross_monthly_income_paise: int
    monthly_debt_paise: int
    requested_amount_paise: int
    tenure_months: int
    annual_rate_bps: int

    state: ApplicationState
    status: WorkflowStatus
    documents: list[DocumentRead] = []
    missing_documents: list[DocumentType] = []
    risk_assessment: RiskAssessmentRead | None = None


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    applicant_name: str
    requested_amount_paise: int
    tenure_months: int
    state: ApplicationState
    status: WorkflowStatus


class WorkflowEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    event_type: EventType
    actor: Actor
    from_state: ApplicationState | None = None
    to_state: ApplicationState | None = None
    payload: dict[str, Any]
    created_at: datetime
