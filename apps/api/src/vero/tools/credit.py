"""Simulated credit bureau.

There is no bureau. Scores come from the application's own seed when a fixture set one,
so a demo can reach a chosen outcome deliberately, and otherwise from a hash of the
application id so that reruns reproduce instead of drifting.

Nothing here contacts a real credit reference agency, and no score produced here means
anything about any real person.
"""

import hashlib
from typing import Any

from vero.tools.executor import ToolContext

MIN_SCORE = 300
MAX_SCORE = 900


def _derive_score(application_id: Any) -> int:
    digest = hashlib.sha256(str(application_id).encode()).digest()
    span = MAX_SCORE - MIN_SCORE
    return MIN_SCORE + (int.from_bytes(digest[:4], "big") % (span + 1))


def run_credit_check(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    app = context.application
    seeded = app.synthetic_credit_score
    score = seeded if seeded is not None else _derive_score(app.id)
    return {
        "credit_score": int(score),
        "source": "SIMULATED",
        "seeded": seeded is not None,
    }
