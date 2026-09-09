"""Persistence for applications and their workflow runs."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vero.db.models import Application, WorkflowRun
from vero.domain.enums import ApplicationState, WorkflowStatus
from vero.domain.money import rupees_to_paise


def _application(**overrides: object) -> Application:
    fields: dict[str, object] = {
        "applicant_name": "Asha Iyer",
        "applicant_email": "asha@example.invalid",
        "gross_monthly_income": rupees_to_paise(Decimal("150000")),
        "monthly_debt": rupees_to_paise(Decimal("35000")),
        "requested_amount": rupees_to_paise(Decimal("800000")),
        "tenure_months": 60,
    }
    fields.update(overrides)
    return Application(**fields)


def test_an_application_round_trips(session: Session) -> None:
    app = _application()
    session.add(app)
    session.flush()

    stored = session.get(Application, app.id)
    assert stored is not None
    assert stored.applicant_name == "Asha Iyer"
    assert stored.gross_monthly_income == 15_000_000


def test_money_is_stored_as_integer_paise(session: Session) -> None:
    """A bigint column, so no float ever reaches the database."""
    app = _application(requested_amount=rupees_to_paise(Decimal("1234.56")))
    session.add(app)
    session.flush()
    assert session.get(Application, app.id).requested_amount == 123_456  # type: ignore[union-attr]


def test_a_new_run_starts_in_received(session: Session) -> None:
    app = _application()
    session.add(app)
    session.flush()

    run = WorkflowRun(application_id=app.id)
    session.add(run)
    session.flush()

    assert run.current_state is ApplicationState.RECEIVED
    assert run.status is WorkflowStatus.RUNNING
    assert run.step_seq == 0
    assert run.document_request_count == 0


def test_state_lives_only_on_the_run(session: Session) -> None:
    """Single source of truth: Application has no state column to drift from."""
    assert not hasattr(Application, "current_state")
    assert not hasattr(Application, "state")


def test_an_application_has_at_most_one_run(session: Session) -> None:
    """One run spans the application's life, so resume continues it rather than forking."""
    app = _application()
    session.add(app)
    session.flush()
    session.add(WorkflowRun(application_id=app.id))
    session.flush()
    session.add(WorkflowRun(application_id=app.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_run_reaches_its_application_through_a_relationship(session: Session) -> None:
    app = _application()
    session.add(app)
    session.flush()
    run = WorkflowRun(application_id=app.id)
    session.add(run)
    session.flush()
    assert run.application.applicant_email == "asha@example.invalid"
