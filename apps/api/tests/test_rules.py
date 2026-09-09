"""The five policy gates.

Boundaries are the whole point of this file. The documented table reads "PASS if
DTI <= 40%, REVIEW 40-50%, FAIL above 50%", so a DTI of exactly 40% passes and exactly
50% reviews: the PASS band owns its edge, and FAIL starts strictly beyond its own.
"""

from decimal import Decimal

import pytest

from vero.domain.money import Paise, rupees_to_paise
from vero.policy.rules import (
    Band,
    evaluate_credit_score,
    evaluate_disposable_income,
    evaluate_dti,
    evaluate_income_divergence,
    evaluate_lti,
)


def _rs(amount: str) -> Paise:
    return rupees_to_paise(Decimal(amount))


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (900, Band.PASS),
        (721, Band.PASS),
        (720, Band.PASS),
        (719, Band.REVIEW),
        (650, Band.REVIEW),
        (649, Band.FAIL),
        (300, Band.FAIL),
    ],
)
def test_credit_score_bands(score: int, expected: Band) -> None:
    assert evaluate_credit_score(score) is expected


@pytest.mark.parametrize(
    ("dti", "expected"),
    [
        ("0.00", Band.PASS),
        ("0.40", Band.PASS),
        ("0.400001", Band.REVIEW),
        ("0.50", Band.REVIEW),
        ("0.500001", Band.FAIL),
        ("1.20", Band.FAIL),
    ],
)
def test_dti_bands(dti: str, expected: Band) -> None:
    assert evaluate_dti(Decimal(dti)) is expected


@pytest.mark.parametrize(
    ("lti", "expected"),
    [
        ("0.44", Band.PASS),
        ("3.5", Band.PASS),
        ("3.500001", Band.REVIEW),
        ("5.0", Band.REVIEW),
        ("5.000001", Band.FAIL),
    ],
)
def test_lti_bands(lti: str, expected: Band) -> None:
    assert evaluate_lti(Decimal(lti)) is expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("96385", Band.PASS),
        ("25000", Band.PASS),
        ("24999.99", Band.REVIEW),
        ("15000", Band.REVIEW),
        ("14999.99", Band.FAIL),
    ],
)
def test_disposable_income_bands(amount: str, expected: Band) -> None:
    assert evaluate_disposable_income(_rs(amount)) is expected


def test_negative_disposable_income_fails() -> None:
    assert evaluate_disposable_income(Paise(-1)) is Band.FAIL


@pytest.mark.parametrize(
    ("gap", "expected"),
    [
        ("0.00", Band.PASS),
        ("0.10", Band.PASS),
        ("0.100001", Band.REVIEW),
        ("0.25", Band.REVIEW),
        ("0.250001", Band.FAIL),
    ],
)
def test_income_divergence_bands(gap: str, expected: Band) -> None:
    assert evaluate_income_divergence(Decimal(gap)) is expected
