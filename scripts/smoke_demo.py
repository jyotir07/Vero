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
from dataclasses import dataclass
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "apps" / "api" / "fixtures" / "documents"
DOCS = [
    ("PAY_SLIP", "payslip.pdf"),
    ("BANK_STATEMENT", "bank-statement.pdf"),
    ("ID_PROOF", "id-proof.pdf"),
]


@dataclass(frozen=True)
class Case:
    label: str
    slug: str
    tenure: int
    score: int | None
    income: int
    debt: int
    amount: int
    expected: str


# One case per fixture applicant, so every generated document set is exercised and each
# of the four outcomes is reached. The two HUMAN_REVIEW cases escalate for different
# reasons: one on a policy band, one on extraction confidence.
CASES = [
    Case(
        label="approves at 60mo",
        slug="asha-approved",
        tenure=60,
        score=742,
        income=15_000_000,
        debt=3_500_000,
        amount=80_000_000,
        expected="APPROVED",
    ),
    Case(
        label="refers at 36mo (DTI)",
        slug="asha-approved",
        tenure=36,
        score=742,
        income=15_000_000,
        debt=3_500_000,
        amount=80_000_000,
        expected="HUMAN_REVIEW",
    ),
    Case(
        label="refers on confidence",
        slug="priya-low-confidence",
        tenure=60,
        score=780,
        income=12_000_000,
        debt=1_000_000,
        amount=30_000_000,
        expected="HUMAN_REVIEW",
    ),
    Case(
        label="rejects on score",
        slug="meera-rejected",
        tenure=60,
        score=600,
        income=6_000_000,
        debt=2_000_000,
        amount=20_000_000,
        expected="REJECTED",
    ),
    Case(
        label="fails on extraction",
        slug="vikram-unreadable",
        tenure=60,
        score=742,
        income=11_000_000,
        debt=1_500_000,
        amount=30_000_000,
        expected="FAILED",
    ),
    # Everything passes except the credit score, so this isolates that band. Values are
    # computed from the policy engine, not guessed: at 12 months the same applicant
    # carries a 73% post-loan DTI and is a hard reject.
    Case(
        label="refers on credit score",
        slug="ravi-referred",
        tenure=60,
        score=700,
        income=9_000_000,
        debt=1_000_000,
        amount=30_000_000,
        expected="HUMAN_REVIEW",
    ),
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


def run_case(base: str, case: Case) -> str:
    created = post_json(
        base,
        "/applications",
        {
            "applicant_name": case.label,
            "applicant_email": "demo@example.com",
            # Stated income matches the fixture payslip, so the income-divergence gate
            # stays clean and the gate the case is actually about is the one that trips.
            "gross_monthly_income_paise": case.income,
            "monthly_debt_paise": case.debt,
            "requested_amount_paise": case.amount,
            "tenure_months": case.tenure,
            "synthetic_credit_score": case.score,
        },
    )
    application_id = created["id"]

    for document_type, filename in DOCS:
        post_file(
            base,
            f"/applications/{application_id}/documents",
            document_type,
            FIXTURES / case.slug / filename,
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
    print(f"  {case.label:<26} {state:<26} {len(events):>3} events")
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

    failures = 0
    for case in CASES:
        try:
            actual = run_case(args.base, case)
        except urllib.error.HTTPError as exc:
            print(f"  {case.label:<26} HTTP {exc.code}: {exc.read()[:200]!r}")
            failures += 1
            continue
        if actual != case.expected:
            print(f"    EXPECTED {case.expected}, GOT {actual}")
            failures += 1

    print()
    if failures:
        print(f"{failures} case(s) did not reach the expected outcome")
    else:
        print("all cases reached their expected outcome")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
