"""Generate synthetic documents for the demo and the test suite.

Every document is fabricated. The names, employers, account numbers and amounts refer to
no real person or institution, and nothing here is derived from real financial data.

Each PDF carries a VERO-FIXTURE marker holding the structured data it depicts, which is
what the fake extractor reads back. The visible page and the marker are generated from
the same values, so what a reviewer sees on screen is what extraction returns.

Usage:
    uv run python ../../scripts/generate_fixtures.py [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

MARKER = "VERO-FIXTURE:"

APPLICANTS: list[dict[str, Any]] = [
    {
        "slug": "asha-approved",
        "name": "Asha Iyer",
        "employer": "Northwind Analytics",
        "monthly_income_paise": 15_000_000,
        "closing_balance_paise": 42_000_000,
        "note": "Spec worked example. Approves at 60 months, refers at 36.",
    },
    {
        "slug": "ravi-referred",
        "name": "Ravi Menon",
        "employer": "Blue Harbour Logistics",
        "monthly_income_paise": 9_000_000,
        "closing_balance_paise": 6_500_000,
        "note": "Thin headroom; lands in the review band.",
    },
    {
        "slug": "meera-rejected",
        "name": "Meera Nair",
        "employer": "Copperleaf Retail",
        "monthly_income_paise": 6_000_000,
        "closing_balance_paise": 800_000,
        "note": "Fails on credit score and affordability.",
    },
    {
        "slug": "vikram-unreadable",
        "name": "Vikram Rao",
        "employer": "Stonebridge Foods",
        "monthly_income_paise": 11_000_000,
        "closing_balance_paise": 15_000_000,
        "fail": True,
        "note": "Payslip fails extraction, exercising DOCUMENT_CHECK -> FAILED.",
    },
    {
        "slug": "priya-low-confidence",
        "name": "Priya Balan",
        "employer": "Fernhill Media",
        "monthly_income_paise": 12_000_000,
        "closing_balance_paise": 20_000_000,
        "confidence": "0.400",
        "note": "Legible but doubtful; routes to human review on confidence.",
    },
]


def _stable_digits(slug: str) -> str:
    """hash() is salted per process, which would rewrite every fixture on each run."""
    return str(int(hashlib.sha256(slug.encode()).hexdigest()[:8], 16) % 10000).zfill(4)


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


def _write_pdf(path: Path, title: str, lines: list[tuple[str, str]], payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # pageCompression=0: the fake extractor reads the marker from the raw bytes, and a
    # compressed content stream would hide it.
    # invariant=1 fixes the embedded timestamps so regenerating produces identical
    # bytes instead of a diff every time.
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, invariant=1)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, height - 25 * mm, title)

    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(20 * mm, height - 32 * mm, "SYNTHETIC DOCUMENT - technical demonstration only.")
    pdf.drawString(20 * mm, height - 37 * mm, "Not a real financial document. No real person or institution.")

    y = height - 55 * mm
    pdf.setFont("Helvetica", 11)
    for label, value in lines:
        pdf.drawString(20 * mm, y, f"{label}:")
        pdf.drawRightString(width - 20 * mm, y, value)
        y -= 8 * mm

    # The structured answer the fake extractor reads back. Kept in the PDF itself so a
    # fixture cannot drift from the page it depicts.
    pdf.setFont("Helvetica", 5)
    pdf.drawString(20 * mm, 12 * mm, MARKER + json.dumps(payload, separators=(",", ":")))
    pdf.save()


def generate(out_dir: Path) -> list[Path]:
    written: list[Path] = []
    index: list[dict[str, Any]] = []

    for applicant in APPLICANTS:
        slug = applicant["slug"]
        folder = out_dir / slug

        payslip_payload: dict[str, Any] = {
            "document_type": "PAY_SLIP",
            "monthly_income_paise": applicant["monthly_income_paise"],
            "employer": applicant["employer"],
        }
        if applicant.get("fail"):
            payslip_payload["fail"] = True
        if applicant.get("confidence"):
            payslip_payload["confidence"] = applicant["confidence"]

        payslip = folder / "payslip.pdf"
        _write_pdf(
            payslip,
            "Monthly Payslip",
            [
                ("Employee", applicant["name"]),
                ("Employer", applicant["employer"]),
                ("Gross monthly pay", _rupees(applicant["monthly_income_paise"])),
                ("Period", "2026-08"),
            ],
            payslip_payload,
        )
        written.append(payslip)

        statement = folder / "bank-statement.pdf"
        _write_pdf(
            statement,
            "Bank Statement",
            [
                ("Account holder", applicant["name"]),
                ("Closing balance", _rupees(applicant["closing_balance_paise"])),
                ("Average monthly credit", _rupees(applicant["monthly_income_paise"])),
                ("Period", "2026-06 to 2026-08"),
            ],
            {
                "document_type": "BANK_STATEMENT",
                "closing_balance_paise": applicant["closing_balance_paise"],
                "average_monthly_credit_paise": applicant["monthly_income_paise"],
            },
        )
        written.append(statement)

        id_proof = folder / "id-proof.pdf"
        _write_pdf(
            id_proof,
            "Identity Document",
            [
                ("Name", applicant["name"]),
                ("Document number", "XXXX-XXXX-" + _stable_digits(slug)),
                ("Issued", "2020-01-01"),
            ],
            {"document_type": "ID_PROOF", "name": applicant["name"]},
        )
        written.append(id_proof)

        index.append({k: v for k, v in applicant.items() if k != "slug"} | {"slug": slug})

    (out_dir / "index.json").write_text(json.dumps(index, indent=2))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "apps" / "api" / "fixtures" / "documents",
    )
    args = parser.parse_args()

    written = generate(args.out)
    print(f"wrote {len(written)} synthetic documents to {args.out}")


if __name__ == "__main__":
    main()
