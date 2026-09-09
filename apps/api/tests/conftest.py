"""Database fixtures.

Tests run against a real PostgreSQL instance, not SQLite: the append-only guarantee on
workflow_event is enforced by a Postgres trigger, and a test suite that never exercises
it would be testing a different database than production uses.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

ADMIN_URL = os.environ.get("VERO_TEST_ADMIN_URL", "postgresql://vero:vero@localhost:5433/vero")
TEST_DB = "vero_test"


def _test_url(driver: str = "postgresql+psycopg") -> str:
    base = ADMIN_URL.split("://", 1)[1].rsplit("/", 1)[0]
    return f"{driver}://{base}/{TEST_DB}"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A disposable vero_test database, rebuilt from the models each session."""
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.OperationalError as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL unavailable at {ADMIN_URL}: {exc}")

    from vero.db.models import Base
    from vero.db.schema import install_append_only_guard

    eng = create_engine(_test_url(), future=True)
    Base.metadata.create_all(eng)
    install_append_only_guard(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """One transaction per test, rolled back afterwards.

    Rollback rather than truncation keeps tests isolated without fighting the
    append-only trigger, which refuses DELETE on workflow_event.
    """
    connection = engine.connect()
    transaction = connection.begin()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as sess:
        yield sess
    transaction.rollback()
    connection.close()
