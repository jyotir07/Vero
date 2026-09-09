"""The synthetic loan product Vero underwrites.

Fixed terms, because the point of the project is the workflow around the decision,
not product configuration.
"""

from decimal import ROUND_HALF_UP, Decimal

from vero.domain.money import Paise, rupees_to_paise

ANNUAL_RATE_BPS = 1400
ALLOWED_TENURES_MONTHS = (12, 24, 36, 48, 60)
MIN_PRINCIPAL = rupees_to_paise(Decimal("50000"))
MAX_PRINCIPAL = rupees_to_paise(Decimal("5000000"))

_BPS_PER_UNIT = Decimal(10_000)
_MONTHS_PER_YEAR = Decimal(12)


def monthly_emi(principal: Paise, *, annual_rate_bps: int, months: int) -> Paise:
    """Equated monthly instalment on a reducing balance.

    EMI = P*r*(1+r)^n / ((1+r)^n - 1), with r the monthly rate. At r = 0 that form is
    undefined, so the straight-line case is handled separately.
    """
    if months not in ALLOWED_TENURES_MONTHS:
        raise ValueError(f"tenure {months} is not offered; allowed: {ALLOWED_TENURES_MONTHS}")

    principal_decimal = Decimal(principal)
    if annual_rate_bps == 0:
        instalment = principal_decimal / Decimal(months)
    else:
        rate = Decimal(annual_rate_bps) / _BPS_PER_UNIT / _MONTHS_PER_YEAR
        growth = (Decimal(1) + rate) ** months
        instalment = principal_decimal * rate * growth / (growth - Decimal(1))

    return Paise(int(instalment.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
