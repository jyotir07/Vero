"""The synthetic policy table.

Five gates, three bands each. The thresholds are invented for this demonstration; they
are not any real lender's underwriting criteria.

Band edges: the PASS band includes its own boundary, and FAIL begins strictly beyond
its own. REVIEW takes everything between. So a DTI of exactly 40% passes and exactly
50% reviews.
"""

from decimal import Decimal
from enum import StrEnum

from vero.domain.money import Paise, rupees_to_paise

MIN_PASS_CREDIT_SCORE = 720
MIN_REVIEW_CREDIT_SCORE = 650

MAX_PASS_DTI = Decimal("0.40")
MAX_REVIEW_DTI = Decimal("0.50")

MAX_PASS_LTI = Decimal("3.5")
MAX_REVIEW_LTI = Decimal("5.0")

MIN_PASS_DISPOSABLE = rupees_to_paise(Decimal("25000"))
MIN_REVIEW_DISPOSABLE = rupees_to_paise(Decimal("15000"))

MAX_PASS_DIVERGENCE = Decimal("0.10")
MAX_REVIEW_DIVERGENCE = Decimal("0.25")


class Band(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


def _band_where_less_is_better(
    value: Decimal | int, *, pass_at_or_below: Decimal | int, review_at_or_below: Decimal | int
) -> Band:
    if value <= pass_at_or_below:
        return Band.PASS
    if value <= review_at_or_below:
        return Band.REVIEW
    return Band.FAIL


def _band_where_more_is_better(
    value: Decimal | int, *, pass_at_or_above: Decimal | int, review_at_or_above: Decimal | int
) -> Band:
    if value >= pass_at_or_above:
        return Band.PASS
    if value >= review_at_or_above:
        return Band.REVIEW
    return Band.FAIL


def evaluate_credit_score(score: int) -> Band:
    return _band_where_more_is_better(
        score,
        pass_at_or_above=MIN_PASS_CREDIT_SCORE,
        review_at_or_above=MIN_REVIEW_CREDIT_SCORE,
    )


def evaluate_dti(dti: Decimal) -> Band:
    return _band_where_less_is_better(
        dti, pass_at_or_below=MAX_PASS_DTI, review_at_or_below=MAX_REVIEW_DTI
    )


def evaluate_lti(lti: Decimal) -> Band:
    return _band_where_less_is_better(
        lti, pass_at_or_below=MAX_PASS_LTI, review_at_or_below=MAX_REVIEW_LTI
    )


def evaluate_disposable_income(amount: Paise) -> Band:
    return _band_where_more_is_better(
        amount,
        pass_at_or_above=MIN_PASS_DISPOSABLE,
        review_at_or_above=MIN_REVIEW_DISPOSABLE,
    )


def evaluate_income_divergence(gap: Decimal) -> Band:
    return _band_where_less_is_better(
        gap, pass_at_or_below=MAX_PASS_DIVERGENCE, review_at_or_below=MAX_REVIEW_DIVERGENCE
    )


class Gate(StrEnum):
    CREDIT_SCORE = "CREDIT_SCORE"
    DTI = "DTI"
    LTI = "LTI"
    DISPOSABLE_INCOME = "DISPOSABLE_INCOME"
    INCOME_DIVERGENCE = "INCOME_DIVERGENCE"
