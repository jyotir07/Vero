"""Database-level guarantees that outlive the application code.

The audit trail is only worth something if it cannot be quietly rewritten. Enforcing
that in Python would mean trusting every future caller, including a migration script or
someone at a psql prompt. A trigger makes it the database's problem instead.
"""

from sqlalchemy import Engine, text

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION vero_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_TRIGGER = """
CREATE OR REPLACE TRIGGER workflow_event_append_only
BEFORE UPDATE OR DELETE ON workflow_event
FOR EACH ROW EXECUTE FUNCTION vero_reject_mutation();
"""

# TRUNCATE does not fire row-level triggers, so the guard above does not see it. Without
# this second trigger the entire audit trail is one statement away from being erased.
APPEND_ONLY_TRUNCATE_TRIGGER = """
CREATE OR REPLACE TRIGGER workflow_event_no_truncate
BEFORE TRUNCATE ON workflow_event
FOR EACH STATEMENT EXECUTE FUNCTION vero_reject_mutation();
"""


def install_append_only_guard(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(APPEND_ONLY_FUNCTION))
        conn.execute(text(APPEND_ONLY_TRIGGER))
        conn.execute(text(APPEND_ONLY_TRUNCATE_TRIGGER))
