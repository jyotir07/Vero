"""Derived underwriting metrics.

All ratios are Decimal so that a band edge (a DTI of exactly 40%) lands where the
policy table says it should.
"""

from decimal import Decimal

from vero.domain.money import Paise

_RATIO_PLACES = Decimal("0.000001")
_MONTHS_PER_YEAR = 12


def debt_to_income(
    *, monthly_debt: Paise, gross_monthly_income: Paise, emi: Paise | int = 0
) -> Decimal:
    """Debt-to-income ratio.

    Called without `emi` this is the applicant's current position, which is the figure
    quoted in the spec. Called with it, this is the position after the loan is granted,
    which is what the policy table gates on.
    """
    if gross_monthly_income <= 0:
        raise ValueError("gross monthly income must be positive to compute DTI")
    return ((Decimal(monthly_debt) + Decimal(emi)) / Decimal(gross_monthly_income)).quantize(
        _RATIO_PLACES
    )


def loan_to_income(*, principal: Paise, gross_monthly_income: Paise) -> Decimal:
    if gross_monthly_income <= 0:
        raise ValueError("gross monthly income must be positive to compute LTI")
    annual_income = Decimal(gross_monthly_income) * _MONTHS_PER_YEAR
    return (Decimal(principal) / annual_income).quantize(_RATIO_PLACES)


def disposable_income(
    *, gross_monthly_income: Paise, monthly_debt: Paise, emi: Paise | int
) -> Paise:
    """What is left each month. Negative when obligations exceed income."""
    return Paise(int(gross_monthly_income) - int(monthly_debt) - int(emi))


def income_divergence(*, stated: Paise, verified: Paise) -> Decimal:
    """Unsigned gap between stated and verified income.

    Unsigned because overstating income and understating it are both reasons to doubt
    the application, even though only one of them flatters the applicant.
    """
    if stated <= 0:
        raise ValueError("stated income must be positive to compute divergence")
    return (abs(Decimal(verified) - Decimal(stated)) / Decimal(stated)).quantize(_RATIO_PLACES)
