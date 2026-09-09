"""The synthetic loan product: 14% p.a. reducing balance, tenure 12-60 months."""

from decimal import Decimal

import pytest

from vero.domain.money import Paise, rupees_to_paise
from vero.policy.product import (
    ALLOWED_TENURES_MONTHS,
    ANNUAL_RATE_BPS,
    MAX_PRINCIPAL,
    MIN_PRINCIPAL,
    monthly_emi,
)


def _rs(amount: str) -> Paise:
    return rupees_to_paise(Decimal(amount))


def test_zero_interest_emi_is_principal_divided_by_tenure() -> None:
    """The one case with an exact closed form that needs no compounding."""
    assert monthly_emi(_rs("120000"), annual_rate_bps=0, months=12) == _rs("10000")


def test_spec_worked_example_emi_at_60_months() -> None:
    """docs example: Rs 800,000 at 14% over 60 months."""
    emi = monthly_emi(_rs("800000"), annual_rate_bps=1400, months=60)
    assert abs(emi - _rs("18615")) < 100  # within one rupee


def test_spec_worked_example_emi_at_36_months() -> None:
    emi = monthly_emi(_rs("800000"), annual_rate_bps=1400, months=36)
    assert abs(emi - _rs("27342")) < 100


def test_total_repaid_exceeds_principal_when_interest_is_charged() -> None:
    principal = _rs("800000")
    assert monthly_emi(principal, annual_rate_bps=1400, months=60) * 60 > principal


def test_a_longer_tenure_lowers_the_instalment() -> None:
    short = monthly_emi(_rs("800000"), annual_rate_bps=1400, months=36)
    long = monthly_emi(_rs("800000"), annual_rate_bps=1400, months=60)
    assert long < short


def test_a_higher_rate_raises_the_instalment() -> None:
    cheap = monthly_emi(_rs("800000"), annual_rate_bps=1000, months=60)
    dear = monthly_emi(_rs("800000"), annual_rate_bps=1800, months=60)
    assert dear > cheap


def test_tenure_outside_the_product_is_rejected() -> None:
    with pytest.raises(ValueError):
        monthly_emi(_rs("800000"), annual_rate_bps=1400, months=7)


def test_product_terms_match_the_documented_policy() -> None:
    assert ANNUAL_RATE_BPS == 1400
    assert ALLOWED_TENURES_MONTHS == (12, 24, 36, 48, 60)
    assert MIN_PRINCIPAL == 5_000_000  # Rs 50,000 in paise
    assert MAX_PRINCIPAL == 500_000_000  # Rs 50,00,000 in paise
