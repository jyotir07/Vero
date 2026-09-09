"""Turns the policy gates into a recommendation.

Deterministic on purpose: this is the part of the workflow the model is never allowed
to influence. The agent may explain a decision, but it cannot make one.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from vero.domain.money import Paise
from vero.policy import metrics
from vero.policy.product import ANNUAL_RATE_BPS, monthly_emi
from vero.policy.rules import (
    Band,
    Gate,
    evaluate_credit_score,
    evaluate_disposable_income,
    evaluate_dti,
    evaluate_income_divergence,
    evaluate_lti,
)


class PolicyOutcome(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REFER = "REFER"


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    band: Band
    value: str


@dataclass(frozen=True)
class PolicyEvaluation:
    gates: tuple[GateResult, ...]
    overall: Band
    outcome: PolicyOutcome
    emi: Paise
    dti_current: Decimal
    dti_proposed: Decimal
    lti: Decimal
    disposable_income: Paise
    income_divergence: Decimal

    @property
    def tripped_gates(self) -> tuple[Gate, ...]:
        return tuple(g.gate for g in self.gates if g.band is not Band.PASS)


def _overall_band(gates: tuple[GateResult, ...]) -> Band:
    """A single failure decides the case; otherwise any doubt sends it to a human."""
    bands = {g.band for g in gates}
    if Band.FAIL in bands:
        return Band.FAIL
    if Band.REVIEW in bands:
        return Band.REVIEW
    return Band.PASS


_OUTCOME_FOR_BAND = {
    Band.PASS: PolicyOutcome.APPROVE,
    Band.REVIEW: PolicyOutcome.REFER,
    Band.FAIL: PolicyOutcome.REJECT,
}


def evaluate_application(
    *,
    credit_score: int,
    gross_monthly_income: Paise,
    verified_monthly_income: Paise,
    monthly_debt: Paise,
    principal: Paise,
    months: int,
    annual_rate_bps: int = ANNUAL_RATE_BPS,
) -> PolicyEvaluation:
    emi = monthly_emi(principal, annual_rate_bps=annual_rate_bps, months=months)

    dti_current = metrics.debt_to_income(
        monthly_debt=monthly_debt, gross_monthly_income=gross_monthly_income
    )
    dti_proposed = metrics.debt_to_income(
        monthly_debt=monthly_debt, gross_monthly_income=gross_monthly_income, emi=emi
    )
    lti = metrics.loan_to_income(principal=principal, gross_monthly_income=gross_monthly_income)
    disposable = metrics.disposable_income(
        gross_monthly_income=gross_monthly_income, monthly_debt=monthly_debt, emi=emi
    )
    divergence = metrics.income_divergence(
        stated=gross_monthly_income, verified=verified_monthly_income
    )

    gates = (
        GateResult(Gate.CREDIT_SCORE, evaluate_credit_score(credit_score), str(credit_score)),
        GateResult(Gate.DTI, evaluate_dti(dti_proposed), str(dti_proposed)),
        GateResult(Gate.LTI, evaluate_lti(lti), str(lti)),
        GateResult(
            Gate.DISPOSABLE_INCOME, evaluate_disposable_income(disposable), str(disposable)
        ),
        GateResult(
            Gate.INCOME_DIVERGENCE, evaluate_income_divergence(divergence), str(divergence)
        ),
    )

    overall = _overall_band(gates)
    return PolicyEvaluation(
        gates=gates,
        overall=overall,
        outcome=_OUTCOME_FOR_BAND[overall],
        emi=emi,
        dti_current=dti_current,
        dti_proposed=dti_proposed,
        lti=lti,
        disposable_income=disposable,
        income_divergence=divergence,
    )
