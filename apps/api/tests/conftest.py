"""Database fixtures.

Tests run against a real PostgreSQL instance, not SQLite: the append-only guarantee on
workflow_event is enforced by a Postgres trigger, and a test suite that never exercises
it would be testing a different database than production uses.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from vero.agent.provider.fake import ProgrammableLLMProvider

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


@pytest.fixture
def cooperative_model() -> "ProgrammableLLMProvider":
    """A model that does the sensible thing for whatever state it is shown.

    Shared by the runner and API tests so both exercise the same agent behaviour.
    """
    from vero.agent.provider.fake import ProgrammableLLMProvider
    from vero.domain.enums import ApplicationState

    def respond(system: str, user: str) -> str:
        payload = json.loads(user)
        state = payload["state"]
        if state == ApplicationState.DOCUMENT_CHECK.value:
            pending = payload["documents"]["unextracted"]
            if pending:
                return json.dumps(
                    {
                        "tool": "extract_document",
                        "arguments": {"document_id": pending[0]},
                        "reasoning": "extract what has arrived",
                    }
                )
            if payload["documents"]["missing"]:
                return json.dumps(
                    {
                        "tool": "request_information",
                        "arguments": {
                            "document_type": payload["documents"]["missing"][0],
                            "reason": "required document is missing",
                        },
                        "reasoning": "ask for what is missing",
                    }
                )
            return json.dumps(
                {"tool": "check_required_documents", "arguments": {}, "reasoning": "confirm"}
            )
        if state == ApplicationState.INCOME_VERIFICATION.value:
            return json.dumps(
                {"tool": "verify_income", "arguments": {}, "reasoning": "check the payslip"}
            )
        return json.dumps({"tool": "get_application", "arguments": {}, "reasoning": "read"})

    return ProgrammableLLMProvider(respond)


@pytest.fixture
def api_client(
    session: Session, tmp_path: Path, cooperative_model: object
) -> Iterator["TestClient"]:
    """The real app, with the model, document store and database swapped for fakes.

    The background workflow task is given a scope that hands back this same test
    session, so what the task writes is visible to the assertions and is rolled back
    with everything else.
    """
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    from vero.api import deps
    from vero.document_ai.fake import FakeDocumentExtractor
    from vero.main import app
    from vero.storage import LocalDiskStorage

    storage = LocalDiskStorage(root=tmp_path / "store")
    extractor = FakeDocumentExtractor()

    @contextmanager
    def test_scope() -> Iterator[Session]:
        yield session

    app.dependency_overrides[deps.get_session] = lambda: session
    app.dependency_overrides[deps.get_storage] = lambda: storage
    app.dependency_overrides[deps.get_extractor] = lambda: extractor
    app.dependency_overrides[deps.get_provider] = lambda: cooperative_model
    app.dependency_overrides[deps.get_session_scope] = lambda: test_scope
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
