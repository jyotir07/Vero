"""Derived underwriting metrics.

The spec's worked example (Rs 150,000 income, Rs 35,000 debt, Rs 800,000 loan) states
a DTI of 23.3%. That figure excludes the new instalment, so it pins dti_current and
tells us nothing about dti_proposed - which is the one policy actually gates on.
"""

from decimal import Decimal

import pytest

from vero.domain.money import Paise, rupees_to_paise
from vero.policy.metrics import (
    debt_to_income,
    disposable_income,
    income_divergence,
    loan_to_income,
)


def _rs(amount: str) -> Paise:
    return rupees_to_paise(Decimal(amount))


def test_dti_current_reproduces_the_figure_stated_in_the_spec() -> None:
    dti = debt_to_income(monthly_debt=_rs("35000"), gross_monthly_income=_rs("150000"))
    assert (dti * 100).quantize(Decimal("0.1")) == Decimal("23.3")


def test_dti_proposed_includes_the_new_instalment() -> None:
    dti = debt_to_income(
        monthly_debt=_rs("35000"), gross_monthly_income=_rs("150000"), emi=_rs("18615")
    )
    assert (dti * 100).quantize(Decimal("0.1")) == Decimal("35.7")


def test_dti_is_undefined_without_income() -> None:
    with pytest.raises(ValueError):
        debt_to_income(monthly_debt=_rs("35000"), gross_monthly_income=_rs("0"))


def test_loan_to_income_is_measured_against_annual_income() -> None:
    lti = loan_to_income(principal=_rs("800000"), gross_monthly_income=_rs("150000"))
    assert lti.quantize(Decimal("0.01")) == Decimal("0.44")


def test_disposable_income_is_what_remains_after_debt_and_instalment() -> None:
    left = disposable_income(
        gross_monthly_income=_rs("150000"), monthly_debt=_rs("35000"), emi=_rs("18615")
    )
    assert left == _rs("96385")


def test_disposable_income_may_go_negative_when_obligations_exceed_income() -> None:
    left = disposable_income(
        gross_monthly_income=_rs("40000"), monthly_debt=_rs("35000"), emi=_rs("18615")
    )
    assert left < 0


def test_income_divergence_measures_the_gap_against_what_was_stated() -> None:
    gap = income_divergence(stated=_rs("150000"), verified=_rs("120000"))
    assert gap.quantize(Decimal("0.01")) == Decimal("0.20")


def test_income_divergence_is_unsigned_so_overstating_and_understating_both_count() -> None:
    over = income_divergence(stated=_rs("100000"), verified=_rs("120000"))
    under = income_divergence(stated=_rs("100000"), verified=_rs("80000"))
    assert over == under == Decimal("0.20")
