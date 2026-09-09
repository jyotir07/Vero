"""The migration and the models must describe the same database.

conftest builds the test schema straight from Base.metadata, so nothing else in the
suite would notice if the migration drifted. This builds a database the way production
does - by running the migration - and then asks Alembic whether anything differs.
"""

import os
import subprocess
from collections.abc import Iterator

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, text

from tests.conftest import ADMIN_URL

MIGRATION_DB = "vero_migration_test"


@pytest.fixture(scope="module")
def migrated_engine() -> Iterator[Engine]:
    base = ADMIN_URL.split("://", 1)[1].rsplit("/", 1)[0]
    url = f"postgresql+psycopg://{base}/{MIGRATION_DB}"
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {MIGRATION_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {MIGRATION_DB}")
    except psycopg.OperationalError as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    # Inherit the full environment: a minimal one breaks socket initialisation on
    # Windows before alembic even starts.
    env = {**os.environ, "DATABASE_URL": url}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    engine = create_engine(url, future=True)
    yield engine
    engine.dispose()


def test_migration_leaves_no_difference_against_the_models(migrated_engine: Engine) -> None:
    from vero.db.models import Base

    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == [], f"migration and models disagree: {diff}"


def test_migration_installs_both_append_only_triggers(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        names = set(
            conn.scalars(
                text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
            ).all()
        )
    assert {"workflow_event_append_only", "workflow_event_no_truncate"} <= names
