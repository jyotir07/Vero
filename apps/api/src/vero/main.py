from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vero.api.deps import SessionDep
from vero.api.routes import applications, documents, events
from vero.config import get_settings

app = FastAPI(
    title="Vero API",
    version="0.1.0",
    description=(
        "Simulated AI credit underwriting agent. This is a technical demonstration "
        "using synthetic data, not a real credit decisioning system."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(events.router)


@app.get("/health", tags=["health"])
def health(session: SessionDep) -> dict[str, str]:
    """Reports the database too.

    The process being up says little: every request that matters needs Postgres, so a
    health check that only proves the event loop is running would keep a broken
    instance in rotation.
    """
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    return {"status": "ok"}
