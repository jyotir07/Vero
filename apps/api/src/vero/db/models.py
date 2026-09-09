"""SQLAlchemy models.

Two rules shape this schema:

1. Money is BigInteger paise. No float column exists anywhere.
2. Current state lives only on WorkflowRun. Application deliberately has no state
   column, so there is no second copy to drift.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from vero.domain.enums import (
    Actor,
    ApplicationState,
    DocumentStatus,
    DocumentType,
    EventType,
    ReviewStatus,
    ToolCallStatus,
    ValidationResult,
    WorkflowStatus,
)
from vero.policy.decision import PolicyOutcome
from vero.policy.rules import Band


class Base(DeclarativeBase):
    pass


def _enum(python_enum: type[Any], name: str) -> Enum:
    # native_enum=False keeps values in a CHECK constraint rather than a Postgres type,
    # so adding a state is an ordinary migration instead of an ALTER TYPE dance.
    return Enum(python_enum, name=name, native_enum=False, length=32, validate_strings=True)


class Application(Base):
    __tablename__ = "application"
    __table_args__ = (
        CheckConstraint("gross_monthly_income > 0", name="ck_application_income_positive"),
        CheckConstraint("monthly_debt >= 0", name="ck_application_debt_non_negative"),
        CheckConstraint("requested_amount > 0", name="ck_application_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    applicant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    applicant_email: Mapped[str] = mapped_column(String(320), nullable=False)

    gross_monthly_income: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_debt: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=1400)

    run: Mapped["WorkflowRun | None"] = relationship(back_populates="application")
    documents: Mapped[list["Document"]] = relationship(back_populates="application")


class WorkflowRun(Base):
    __tablename__ = "workflow_run"
    __table_args__ = (UniqueConstraint("application_id", name="uq_workflow_run_application"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    current_state: Mapped[ApplicationState] = mapped_column(
        _enum(ApplicationState, "application_state"),
        nullable=False,
        default=ApplicationState.RECEIVED,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        _enum(WorkflowStatus, "workflow_status"), nullable=False, default=WorkflowStatus.RUNNING
    )
    step_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    application: Mapped[Application] = relationship(back_populates="run")


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("application_id", "content_hash", name="uq_document_content"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        _enum(DocumentType, "document_type"), nullable=False
    )
    storage_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), nullable=False, default=DocumentStatus.UPLOADED
    )
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    application: Mapped[Application] = relationship(back_populates="documents")


class WorkflowEvent(Base):
    """Append-only. A database trigger rejects UPDATE and DELETE on this table."""

    __tablename__ = "workflow_event"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "seq", name="uq_workflow_event_seq"),
        Index("ix_workflow_event_application", "application_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"), nullable=False)
    actor: Mapped[Actor] = mapped_column(_enum(Actor, "actor"), nullable=False)
    from_state: Mapped[ApplicationState | None] = mapped_column(
        _enum(ApplicationState, "application_state"), nullable=True
    )
    to_state: Mapped[ApplicationState | None] = mapped_column(
        _enum(ApplicationState, "application_state"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AgentAction(Base):
    """Every proposal the model made, including the ones that were refused."""

    __tablename__ = "agent_action"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )
    step_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    state_at_proposal: Mapped[ApplicationState] = mapped_column(
        _enum(ApplicationState, "application_state"), nullable=False
    )
    proposed_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    validation_result: Mapped[ValidationResult] = mapped_column(
        _enum(ValidationResult, "validation_result"), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ToolCall(Base):
    __tablename__ = "tool_call"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_tool_call_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )
    agent_action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_action.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ToolCallStatus] = mapped_column(
        _enum(ToolCallStatus, "tool_call_status"), nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )

    credit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    emi: Mapped[int] = mapped_column(BigInteger, nullable=False)
    disposable_income: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dti_current: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    dti_proposed: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    lti: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    income_divergence: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)

    gate_bands: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    overall: Mapped[Band] = mapped_column(_enum(Band, "band"), nullable=False)
    outcome: Mapped[PolicyOutcome] = mapped_column(
        _enum(PolicyOutcome, "policy_outcome"), nullable=False
    )
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)


class HumanReview(Base):
    __tablename__ = "human_review"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_gates: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"), nullable=False, default=ReviewStatus.PENDING
    )
