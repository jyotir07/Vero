"""The HTTP surface, end to end.

These are the only tests that exercise intake, the agent, the tools, the state machine
and the audit trail together. Everything below them is a fake, but nothing is stubbed:
the workflow really runs.
"""

import json

from fastapi.testclient import TestClient

from vero.document_ai.fake import FIXTURE_MARKER


def _pdf(payload: dict[str, object]) -> bytes:
    return b"%PDF-1.4 synthetic\n" + FIXTURE_MARKER + json.dumps(payload).encode() + b"\n"


APPLICANT = {
    "applicant_name": "Asha Iyer",
    "applicant_email": "asha@example.com",
    "gross_monthly_income_paise": 15_000_000,
    "monthly_debt_paise": 3_500_000,
    "requested_amount_paise": 80_000_000,
    "tenure_months": 60,
    "synthetic_credit_score": 742,
}


def _create(client: TestClient, **overrides: object) -> dict:
    response = client.post("/applications", json={**APPLICANT, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client: TestClient, application_id: str, doc_type: str, payload: dict) -> None:
    response = client.post(
        f"/applications/{application_id}/documents",
        files={"file": (f"{doc_type.lower()}.pdf", _pdf(payload), "application/pdf")},
        data={"document_type": doc_type},
    )
    assert response.status_code == 201, response.text


def _upload_full_set(client: TestClient, application_id: str, income: int = 15_000_000) -> None:
    _upload(client, application_id, "PAY_SLIP",
            {"document_type": "PAY_SLIP", "monthly_income_paise": income})
    _upload(client, application_id, "BANK_STATEMENT",
            {"document_type": "BANK_STATEMENT", "closing_balance_paise": 42_000_000})
    _upload(client, application_id, "ID_PROOF",
            {"document_type": "ID_PROOF", "name": "Asha Iyer"})


def test_health_is_reported(api_client: TestClient) -> None:
    assert api_client.get("/health").json() == {"status": "ok"}


def test_a_new_application_starts_in_received(api_client: TestClient) -> None:
    created = _create(api_client)
    assert created["state"] == "RECEIVED"
    assert created["status"] == "RUNNING"


def test_intake_rejects_an_unoffered_tenure(api_client: TestClient) -> None:
    response = api_client.post("/applications", json={**APPLICANT, "tenure_months": 7})
    assert response.status_code == 422


def test_intake_rejects_an_amount_outside_the_product(api_client: TestClient) -> None:
    response = api_client.post(
        "/applications", json={**APPLICANT, "requested_amount_paise": 1_000}
    )
    assert response.status_code == 422


def test_intake_rejects_a_negative_amount(api_client: TestClient) -> None:
    response = api_client.post("/applications", json={**APPLICANT, "monthly_debt_paise": -1})
    assert response.status_code == 422


def test_an_unknown_application_is_a_404(api_client: TestClient) -> None:
    assert api_client.get("/applications/11111111-1111-1111-1111-111111111111").status_code == 404


def test_a_malformed_id_is_a_422_not_a_500(api_client: TestClient) -> None:
    assert api_client.get("/applications/not-a-uuid").status_code == 422


def test_applications_are_listed_newest_first(api_client: TestClient) -> None:
    first = _create(api_client)
    second = _create(api_client, applicant_name="Ravi Menon")
    listed = api_client.get("/applications").json()
    assert [a["id"] for a in listed][:2] == [second["id"], first["id"]]


def test_a_complete_application_is_approved(api_client: TestClient) -> None:
    """Scene 1 to 4 of the demo, driven entirely through HTTP."""
    created = _create(api_client)
    _upload_full_set(api_client, created["id"])

    application = api_client.get(f"/applications/{created['id']}").json()
    assert application["state"] == "APPROVED"
    assert application["status"] == "COMPLETED"


def test_an_approved_application_reports_what_decided_it(api_client: TestClient) -> None:
    created = _create(api_client)
    _upload_full_set(api_client, created["id"])
    application = api_client.get(f"/applications/{created['id']}").json()

    assessment = application["risk_assessment"]
    assert assessment["credit_score"] == 742
    assert assessment["dti_proposed"] == "0.357431"
    assert assessment["outcome"] == "APPROVE"


def test_the_same_applicant_over_36_months_reaches_human_review(
    api_client: TestClient,
) -> None:
    created = _create(api_client, tenure_months=36)
    _upload_full_set(api_client, created["id"])
    application = api_client.get(f"/applications/{created['id']}").json()
    assert application["state"] == "HUMAN_REVIEW"
    assert application["status"] == "PAUSED"


def test_a_weak_applicant_is_rejected(api_client: TestClient) -> None:
    created = _create(api_client, synthetic_credit_score=600)
    _upload_full_set(api_client, created["id"])
    assert api_client.get(f"/applications/{created['id']}").json()["state"] == "REJECTED"


def test_a_missing_document_is_requested(api_client: TestClient) -> None:
    """Scene 3: an incomplete application asks for what it needs."""
    created = _create(api_client)
    _upload(api_client, created["id"], "PAY_SLIP",
            {"document_type": "PAY_SLIP", "monthly_income_paise": 15_000_000})
    _upload(api_client, created["id"], "ID_PROOF",
            {"document_type": "ID_PROOF", "name": "Asha Iyer"})

    application = api_client.get(f"/applications/{created['id']}").json()
    assert application["state"] == "MORE_INFORMATION_REQUIRED"
    assert application["missing_documents"] == ["BANK_STATEMENT"]


def test_supplying_the_missing_document_completes_the_application(
    api_client: TestClient,
) -> None:
    """The MORE_INFORMATION_REQUIRED loop closing, which is the point of the state."""
    created = _create(api_client)
    _upload(api_client, created["id"], "PAY_SLIP",
            {"document_type": "PAY_SLIP", "monthly_income_paise": 15_000_000})
    _upload(api_client, created["id"], "ID_PROOF",
            {"document_type": "ID_PROOF", "name": "Asha Iyer"})
    assert api_client.get(f"/applications/{created['id']}").json()["state"] == (
        "MORE_INFORMATION_REQUIRED"
    )

    _upload(api_client, created["id"], "BANK_STATEMENT",
            {"document_type": "BANK_STATEMENT", "closing_balance_paise": 42_000_000})
    assert api_client.get(f"/applications/{created['id']}").json()["state"] == "APPROVED"


def test_an_applicant_who_keeps_sending_the_wrong_thing_eventually_fails(
    api_client: TestClient,
) -> None:
    """The loop bound from docs/plan.md, reached the way a real applicant would reach it."""
    created = _create(api_client)
    _upload(api_client, created["id"], "PAY_SLIP",
            {"document_type": "PAY_SLIP", "monthly_income_paise": 15_000_000})
    _upload(api_client, created["id"], "ID_PROOF",
            {"document_type": "ID_PROOF", "name": "Asha Iyer"})

    for attempt in range(5):
        state = api_client.get(f"/applications/{created['id']}").json()["state"]
        if state == "FAILED":
            break
        _upload(api_client, created["id"], "PAY_SLIP",
                {"document_type": "PAY_SLIP", "monthly_income_paise": 15_000_000 + attempt})

    assert api_client.get(f"/applications/{created['id']}").json()["state"] == "FAILED"


def test_an_unreadable_document_fails_the_application(api_client: TestClient) -> None:
    created = _create(api_client)
    _upload(api_client, created["id"], "PAY_SLIP", {"document_type": "PAY_SLIP", "fail": True})
    _upload(api_client, created["id"], "BANK_STATEMENT",
            {"document_type": "BANK_STATEMENT", "closing_balance_paise": 1})
    _upload(api_client, created["id"], "ID_PROOF",
            {"document_type": "ID_PROOF", "name": "Asha Iyer"})
    assert api_client.get(f"/applications/{created['id']}").json()["state"] == "FAILED"


def test_a_non_pdf_upload_is_refused(api_client: TestClient) -> None:
    """Uploads are untrusted input, so the content is checked and not just the name."""
    created = _create(api_client)
    response = api_client.post(
        f"/applications/{created['id']}/documents",
        files={"file": ("payslip.pdf", b"MZ\x90\x00 this is an executable", "application/pdf")},
        data={"document_type": "PAY_SLIP"},
    )
    assert response.status_code == 422


def test_an_oversized_upload_is_refused(api_client: TestClient) -> None:
    created = _create(api_client)
    response = api_client.post(
        f"/applications/{created['id']}/documents",
        files={"file": ("big.pdf", b"%PDF-1.4\n" + b"x" * (6 * 1024 * 1024), "application/pdf")},
        data={"document_type": "PAY_SLIP"},
    )
    assert response.status_code == 413


def test_the_timeline_reads_as_a_story(api_client: TestClient) -> None:
    """Spec section 9 wants a timeline that proves the system is genuinely stateful."""
    created = _create(api_client)
    _upload_full_set(api_client, created["id"])

    events = api_client.get(f"/applications/{created['id']}/events").json()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    transitions = [e for e in events if e["event_type"] == "STATE_CHANGED"]
    assert transitions[0]["from_state"] == "RECEIVED"
    assert transitions[-1]["to_state"] == "APPROVED"


def test_the_timeline_records_who_did_what(api_client: TestClient) -> None:
    created = _create(api_client)
    _upload_full_set(api_client, created["id"])
    events = api_client.get(f"/applications/{created['id']}/events").json()
    actors = {e["actor"] for e in events}
    assert "AGENT" in actors
    assert "SYSTEM" in actors


def test_events_for_an_unknown_application_are_a_404(api_client: TestClient) -> None:
    response = api_client.get("/applications/11111111-1111-1111-1111-111111111111/events")
    assert response.status_code == 404


def test_documents_are_reported_with_their_extraction_state(api_client: TestClient) -> None:
    created = _create(api_client)
    _upload_full_set(api_client, created["id"])
    application = api_client.get(f"/applications/{created['id']}").json()
    assert {d["document_type"] for d in application["documents"]} == {
        "PAY_SLIP",
        "BANK_STATEMENT",
        "ID_PROOF",
    }
    assert all(d["status"] == "EXTRACTED" for d in application["documents"])


def test_the_openapi_schema_is_served(api_client: TestClient) -> None:
    """The frontend generates its types from this, so it has to be reachable."""
    schema = api_client.get("/openapi.json").json()
    assert "/applications" in schema["paths"]
