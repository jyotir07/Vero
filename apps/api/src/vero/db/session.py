"""Database engine and session factory.

Connections carry a statement and lock timeout. Spec section 12 wants every external
dependency bounded, and the database is the one a tool can genuinely hang on: a
statement waiting on a row lock will otherwise wait forever, which is how the API
deadlocked itself during Phase 1 when a background task blocked on a request's lock.

The timeout is enforced by Postgres rather than by Python. A thread with a deadline
cannot help here — handlers use the session, SQLAlchemy sessions are not thread-safe,
and abandoning a thread that is still writing would leave the session corrupted.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from vero.config import Settings, get_settings

_engine: Engine | None = None


def _timeout_options(settings: Settings) -> dict[str, str]:
    """Postgres server settings applied to every connection.

    A value of zero disables the limit, which is what a migration or a deliberately long
    job needs.
    """
    milliseconds = int(settings.db_statement_timeout_seconds * 1000)
    return {
        "options": f"-c statement_timeout={milliseconds} -c lock_timeout={milliseconds}"
    }


def create_app_engine(settings: Settings | None = None) -> Engine:
    resolved = settings if settings is not None else get_settings()
    return create_engine(
        resolved.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=_timeout_options(resolved),
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_app_engine()
    return _engine


def session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on failure.

    Used by the background worker, which runs outside the request and therefore outside
    any dependency-managed session.
    """
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
