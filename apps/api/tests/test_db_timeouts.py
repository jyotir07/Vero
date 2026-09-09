"""Database statement and lock timeouts.

Spec section 12 requires every external dependency to have a timeout. The tool layer
had a `tool_timeout_seconds` setting that nothing ever read, which is worse than having
none: it reads as a guarantee.

Wrapping a handler in a thread with a deadline would not work here. Handlers use the
request's SQLAlchemy session, which is not thread-safe, so abandoning one thread while
it keeps writing would corrupt session state. What can actually hang in Phase 1 is a
database statement waiting on a lock - the deadlock that took the API down during M8 -
and Postgres can bound that itself.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from vero.config import Settings
from vero.db.session import create_app_engine


def test_the_statement_timeout_is_applied_to_connections() -> None:
    engine = create_app_engine(Settings(db_statement_timeout_seconds=7))
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SHOW statement_timeout")) == "7s"
    finally:
        engine.dispose()


def test_the_lock_timeout_is_applied_to_connections() -> None:
    engine = create_app_engine(Settings(db_statement_timeout_seconds=7))
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SHOW lock_timeout")) == "7s"
    finally:
        engine.dispose()


def test_a_statement_that_runs_too_long_is_cancelled() -> None:
    """The guarantee has to be real, not merely configured."""
    engine = create_app_engine(Settings(db_statement_timeout_seconds=1))
    try:
        with engine.connect() as conn, pytest.raises(OperationalError) as excinfo:
            conn.execute(text("SELECT pg_sleep(5)"))
        from psycopg.errors import QueryCanceled

        assert isinstance(excinfo.value.orig, QueryCanceled)
    finally:
        engine.dispose()


def test_a_zero_timeout_disables_the_limit() -> None:
    """An escape hatch for a migration or a deliberate long job."""
    engine = create_app_engine(Settings(db_statement_timeout_seconds=0))
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SHOW statement_timeout")) == "0"
    finally:
        engine.dispose()


def test_the_unused_tool_timeout_setting_is_gone() -> None:
    """It was declared and never read, which reads as a guarantee that did not exist."""
    assert not hasattr(Settings(), "tool_timeout_seconds")
