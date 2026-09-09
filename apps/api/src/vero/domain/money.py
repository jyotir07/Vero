"""Integer paise, never float.

Policy bands are decided on exact boundaries, so every amount is an int and every
ratio is a Decimal. Introducing a float anywhere in this path reintroduces the
rounding surprises the band edges are meant to be safe from.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import NewType

Paise = NewType("Paise", int)

_PAISE_PER_RUPEE = Decimal(100)


def rupees_to_paise(amount: Decimal) -> Paise:
    if amount < 0:
        raise ValueError(f"amount may not be negative: {amount}")
    return Paise(int((amount * _PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def paise_to_rupees(amount: Paise | int) -> Decimal:
    return (Decimal(amount) / _PAISE_PER_RUPEE).quantize(Decimal("0.01"))


def format_inr(amount: Paise | int) -> str:
    return f"Rs {paise_to_rupees(amount):,.2f}"
