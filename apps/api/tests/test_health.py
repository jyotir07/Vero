"""Health reports the database, so both answers are exercised with a stand-in session."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from vero.api.deps import get_session
from vero.main import app


class _Session:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def execute(self, statement: object) -> None:
        if self._error is not None:
            raise self._error

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.pop(get_session, None)


def _use(session: _Session) -> None:
    app.dependency_overrides[get_session] = lambda: session


def test_health_returns_ok_when_the_database_answers(client: TestClient) -> None:
    _use(_Session())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_unavailable_when_the_database_is_down(client: TestClient) -> None:
    _use(_Session(OperationalError("SELECT 1", {}, Exception("connection refused"))))
    assert client.get("/health").status_code == 503
