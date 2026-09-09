"""The audit trail.

An audit log that can be edited is not an audit log, so immutability is enforced by a
database trigger rather than by convention in the application layer.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vero.db.models import Application, WorkflowEvent, WorkflowRun
from vero.domain.enums import Actor, ApplicationState, EventType
from vero.domain.money import rupees_to_paise
from vero.events.recorder import EventRecorder


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
    workflow_run = WorkflowRun(application_id=app.id)
    session.add(workflow_run)
    session.flush()
    return workflow_run


def test_the_first_event_is_sequence_one(session: Session, run: WorkflowRun) -> None:
    event = EventRecorder(session).record(
        run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM
    )
    assert event.seq == 1


def test_sequence_numbers_increment_without_gaps(session: Session, run: WorkflowRun) -> None:
    recorder = EventRecorder(session)
    seqs = [
        recorder.record(run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM).seq
        for _ in range(5)
    ]
    assert seqs == [1, 2, 3, 4, 5]


def test_a_state_change_records_both_ends_of_the_move(
    session: Session, run: WorkflowRun
) -> None:
    event = EventRecorder(session).record(
        run=run,
        event_type=EventType.STATE_CHANGED,
        actor=Actor.SYSTEM,
        from_state=ApplicationState.RECEIVED,
        to_state=ApplicationState.DOCUMENT_CHECK,
    )
    assert event.from_state is ApplicationState.RECEIVED
    assert event.to_state is ApplicationState.DOCUMENT_CHECK


def test_an_event_is_traceable_to_its_application(session: Session, run: WorkflowRun) -> None:
    event = EventRecorder(session).record(
        run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM
    )
    assert event.application_id == run.application_id


def test_payload_defaults_to_empty_rather_than_null(
    session: Session, run: WorkflowRun
) -> None:
    event = EventRecorder(session).record(
        run=run, event_type=EventType.POLICY_EVALUATED, actor=Actor.SYSTEM
    )
    assert event.payload == {}


def test_payload_round_trips_structured_data(session: Session, run: WorkflowRun) -> None:
    event = EventRecorder(session).record(
        run=run,
        event_type=EventType.POLICY_EVALUATED,
        actor=Actor.SYSTEM,
        payload={"tripped": ["DTI"], "dti_proposed": "0.415614"},
    )
    session.flush()
    session.expire(event)
    assert event.payload["tripped"] == ["DTI"]


def test_an_event_cannot_be_updated(session: Session, run: WorkflowRun) -> None:
    event = EventRecorder(session).record(
        run=run, event_type=EventType.DECISION_MADE, actor=Actor.SYSTEM
    )
    session.flush()
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(
            text("UPDATE workflow_event SET actor = 'APPLICANT' WHERE id = :id"),
            {"id": event.id},
        )


def test_an_event_cannot_be_deleted(session: Session, run: WorkflowRun) -> None:
    event = EventRecorder(session).record(
        run=run, event_type=EventType.DECISION_MADE, actor=Actor.SYSTEM
    )
    session.flush()
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(text("DELETE FROM workflow_event WHERE id = :id"), {"id": event.id})


def test_two_events_cannot_share_a_sequence_number(
    session: Session, run: WorkflowRun
) -> None:
    """The unique constraint is the backstop if sequence assignment ever races."""
    EventRecorder(session).record(
        run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM
    )
    session.flush()
    session.add(
        WorkflowEvent(
            application_id=run.application_id,
            workflow_run_id=run.id,
            seq=1,
            event_type=EventType.STATE_CHANGED,
            actor=Actor.SYSTEM,
            payload={},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_sequences_are_scoped_to_their_own_run(session: Session, run: WorkflowRun) -> None:
    other_app = Application(
        applicant_name="Ravi Menon",
        applicant_email="ravi@example.com",
        gross_monthly_income=rupees_to_paise(Decimal("90000")),
        monthly_debt=rupees_to_paise(Decimal("10000")),
        requested_amount=rupees_to_paise(Decimal("300000")),
        tenure_months=36,
    )
    session.add(other_app)
    session.flush()
    other_run = WorkflowRun(application_id=other_app.id)
    session.add(other_run)
    session.flush()

    recorder = EventRecorder(session)
    recorder.record(run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM)
    recorder.record(run=run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM)
    first_on_other = recorder.record(
        run=other_run, event_type=EventType.STATE_CHANGED, actor=Actor.SYSTEM
    )
    assert first_on_other.seq == 1


def test_the_event_log_cannot_be_truncated(session: Session, run: WorkflowRun) -> None:
    """TRUNCATE bypasses row-level triggers entirely, so it needs its own guard.

    Without this the whole audit trail is one statement away from being erased, which
    would make the DELETE and UPDATE guards above worth very little.
    """
    EventRecorder(session).record(
        run=run, event_type=EventType.DECISION_MADE, actor=Actor.SYSTEM
    )
    session.flush()
    with pytest.raises(IntegrityError, match="append-only"):
        session.execute(text("TRUNCATE workflow_event"))
