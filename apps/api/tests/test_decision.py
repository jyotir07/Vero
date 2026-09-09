"""End-to-end policy evaluation and the resulting recommendation.

Calibration target from docs/plan.md: the spec's worked applicant approves cleanly at
60 months and lands in review at 36 months. Same person, same loan, different tenure -
which is what makes it a usable demo without inventing a contrived fixture.
"""

from decimal import Decimal

import pytest

from vero.domain.money import Paise, rupees_to_paise
from vero.policy.decision import PolicyOutcome, evaluate_application
from vero.policy.rules import Band, Gate


def _rs(amount: str) -> Paise:
    return rupees_to_paise(Decimal(amount))


def _spec_applicant(months: int, **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "credit_score": 742,
        "gross_monthly_income": _rs("150000"),
        "verified_monthly_income": _rs("150000"),
        "monthly_debt": _rs("35000"),
        "principal": _rs("800000"),
        "months": months,
    }
    kwargs.update(overrides)
    return evaluate_application(**kwargs)  # type: ignore[arg-type]


def test_spec_applicant_is_approved_over_sixty_months() -> None:
    result = _spec_applicant(60)
    assert result.overall is Band.PASS
    assert result.outcome is PolicyOutcome.APPROVE
    assert result.tripped_gates == ()


def test_spec_applicant_is_referred_over_thirty_six_months() -> None:
    """The shorter tenure raises the instalment and pushes DTI into the review band."""
    result = _spec_applicant(36)
    assert result.overall is Band.REVIEW
    assert result.outcome is PolicyOutcome.REFER
    assert result.tripped_gates == (Gate.DTI,)


def test_evaluation_reports_the_metrics_it_decided_on() -> None:
    """Exact paise, not the rupee-rounded Rs 18,615 quoted in docs/plan.md."""
    result = _spec_applicant(60)
    assert result.emi == _rs("18614.60")
    assert (result.dti_current * 100).quantize(Decimal("0.1")) == Decimal("23.3")
    assert (result.dti_proposed * 100).quantize(Decimal("0.1")) == Decimal("35.7")
    assert result.disposable_income == _rs("96385.40")


def test_a_failing_gate_rejects_outright_without_human_review() -> None:
    result = _spec_applicant(60, credit_score=600)
    assert result.outcome is PolicyOutcome.REJECT
    assert result.tripped_gates == (Gate.CREDIT_SCORE,)


def test_a_failure_outranks_a_referral() -> None:
    """One FAIL decides the case even when other gates only warrant review."""
    result = _spec_applicant(36, credit_score=600)
    assert result.overall is Band.FAIL
    assert result.outcome is PolicyOutcome.REJECT
    assert set(result.tripped_gates) == {Gate.CREDIT_SCORE, Gate.DTI}


def test_unverified_income_refers_rather_than_rejecting() -> None:
    result = _spec_applicant(60, verified_monthly_income=_rs("130000"))
    assert result.outcome is PolicyOutcome.REFER
    assert result.tripped_gates == (Gate.INCOME_DIVERGENCE,)


def test_wildly_unverified_income_fails() -> None:
    result = _spec_applicant(60, verified_monthly_income=_rs("100000"))
    assert result.outcome is PolicyOutcome.REJECT


def test_every_gate_is_evaluated_and_reported() -> None:
    result = _spec_applicant(60)
    assert tuple(g.gate for g in result.gates) == tuple(Gate)


def test_an_unoffered_tenure_is_rejected_before_any_gate_runs() -> None:
    with pytest.raises(ValueError):
        _spec_applicant(7)
