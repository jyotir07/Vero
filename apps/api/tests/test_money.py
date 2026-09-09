"""Money is stored as integer paise. Nothing in the policy path may touch float.

Band edges (a DTI of exactly 40%) decide outcomes, so rounding has to be exact and
predictable rather than whatever binary floating point happens to do.
"""

from decimal import Decimal

import pytest

from vero.domain.money import format_inr, paise_to_rupees, rupees_to_paise


def test_whole_rupees_convert_to_paise() -> None:
    assert rupees_to_paise(Decimal("150000")) == 15_000_000


def test_fractional_rupees_keep_paise_precision() -> None:
    assert rupees_to_paise(Decimal("1234.56")) == 123_456


def test_sub_paise_amounts_round_half_up() -> None:
    assert rupees_to_paise(Decimal("0.005")) == 1
    assert rupees_to_paise(Decimal("0.004")) == 0


def test_paise_convert_back_to_rupees_exactly() -> None:
    assert paise_to_rupees(123_456) == Decimal("1234.56")


def test_negative_amounts_are_rejected() -> None:
    with pytest.raises(ValueError):
        rupees_to_paise(Decimal("-1"))


def test_format_inr_is_human_readable() -> None:
    assert format_inr(1_861_500) == "Rs 18,615.00"
