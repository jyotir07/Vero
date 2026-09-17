import pytest
from fastapi.testclient import TestClient

from vero.config import Settings
from vero.main import app

client = TestClient(app)


def _preflight(origin: str) -> dict[str, str]:
    response = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    return dict(response.headers)


def test_the_local_frontend_is_allowed_by_default() -> None:
    headers = _preflight("http://localhost:5173")
    assert headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_an_unlisted_origin_is_not_allowed() -> None:
    assert "access-control-allow-origin" not in _preflight("https://evil.example")


def test_origins_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", '["https://vero.example", "http://localhost:5173"]')
    assert Settings().cors_origins == ["https://vero.example", "http://localhost:5173"]
