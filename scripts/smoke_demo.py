"""Drive a full application through the running stack, the way the UI does.

Talks to the Vite dev server's /api proxy rather than the backend directly, so this
exercises the same path the browser takes. Uses the generated fixture PDFs, so document
extraction is doing real work on real files.

Usage:
    uv run python ../../scripts/smoke_demo.py [--base http://localhost:5173/api]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "apps" / "api" / "fixtures" / "documents"
DOCS = [
    ("PAY_SLIP", "payslip.pdf"),
    ("BANK_STATEMENT", "bank-statement.pdf"),
    ("ID_PROOF", "id-proof.pdf"),
]


def post_json(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def get_json(base: str, path: str) -> dict | list:
    with urllib.request.urlopen(f"{base}{path}", timeout=30) as response:
        return json.load(response)


def post_file(base: str, path: str, document_type: str, file_path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = b""
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="document_type"\r\n\r\n'.encode()
    body += f"{document_type}\r\n".encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{file_path.name}"\r\nContent-Type: application/pdf\r\n\r\n'
    ).encode()
    body += file_path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def run_case(base: str, label: str, slug: str, tenure: int, score: int | None) -> str:
    created = post_json(
        base,
        "/applications",
        {
            "applicant_name": label,
            "applicant_email": "demo@example.com",
            "gross_monthly_income_paise": 15_000_000,
            "monthly_debt_paise": 3_500_000,
            "requested_amount_paise": 80_000_000,
            "tenure_months": tenure,
            "synthetic_credit_score": score,
        },
    )
    application_id = created["id"]

    for document_type, filename in DOCS:
        post_file(
            base,
            f"/applications/{application_id}/documents",
            document_type,
            FIXTURES / slug / filename,
        )

    # An upload returns before its background task finishes, so a waiting state may
    # simply be one the workflow has not left yet. Terminal states stop immediately;
    # a waiting state has to hold still before it counts as the answer.
    terminal = {"APPROVED", "REJECTED", "FAILED"}
    waiting = {"HUMAN_REVIEW", "MORE_INFORMATION_REQUIRED"}
    deadline = time.time() + 30
    state = created["state"]
    stable = 0
    while time.time() < deadline:
        application = get_json(base, f"/applications/{application_id}")
        assert isinstance(application, dict)
        latest = application["state"]
        if latest in terminal:
            state = latest
            break
        stable = stable + 1 if latest == state and latest in waiting else 0
        state = latest
        if stable >= 4:
            break
        time.sleep(0.5)

    events = get_json(base, f"/applications/{application_id}/events")
    assert isinstance(events, list)
    transitions = [e for e in events if e["event_type"] == "STATE_CHANGED"]
    chain = " -> ".join([transitions[0]["from_state"], *[e["to_state"] for e in transitions]])
    print(f"  {label:<22} {state:<26} {len(events):>3} events")
    print(f"    {chain}")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:5173/api")
    args = parser.parse_args()

    if not FIXTURES.exists():
        print("fixtures missing; run scripts/generate_fixtures.py", file=sys.stderr)
        return 1

    print(f"driving the stack through {args.base}\n")
    cases = [
        ("approves at 60mo", "asha-approved", 60, 742, "APPROVED"),
        ("refers at 36mo", "asha-approved", 36, 742, "HUMAN_REVIEW"),
        ("rejects on score", "asha-approved", 60, 600, "REJECTED"),
        ("fails on extraction", "vikram-unreadable", 60, 742, "FAILED"),
    ]

    failures = 0
    for label, slug, tenure, score, expected in cases:
        try:
            actual = run_case(args.base, label, slug, tenure, score)
        except urllib.error.HTTPError as exc:
            print(f"  {label:<22} HTTP {exc.code}: {exc.read()[:200]!r}")
            failures += 1
            continue
        if actual != expected:
            print(f"    EXPECTED {expected}, GOT {actual}")
            failures += 1

    print()
    print("all cases reached their expected outcome" if not failures else f"{failures} case(s) wrong")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
