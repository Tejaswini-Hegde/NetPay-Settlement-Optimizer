"""Exact monetary values using integer units of 1/10,000."""
from decimal import Decimal, InvalidOperation

from babel.core import get_global
from babel.numbers import get_currency_precision

UNITS_PER_CURRENCY = 10_000
CURRENCY_CODES = frozenset(get_global("all_currencies")) - {"XXX"}


def currency_precision(currency: str) -> int:
    """Return CLDR minor-unit precision for a recognized ISO currency code."""
    code = currency.strip().upper()
    if code not in CURRENCY_CODES:
        raise ValueError(f"unknown ISO 4217 currency code: {currency!r}")
    precision = get_currency_precision(code)
    if precision > 4:
        raise ValueError(
            f"{code} requires {precision} decimal places, but the internal "
            "money representation supports at most 4."
        )
    return precision


def to_units(value, currency: str | None = None) -> int:
    """Convert a decimal amount to 1/10,000 units without rounding."""
    if currency is not None:
        currency_precision(currency)
    try:
        amount = Decimal(str(value))
        scaled = amount * UNITS_PER_CURRENCY
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid monetary amount: {value!r}") from None
    if not amount.is_finite() or scaled != scaled.to_integral_value():
        raise ValueError("monetary amounts may have at most 4 decimal places")
    return int(scaled)


def format_amount(units: int) -> str:
    """Format 1/10,000 units as a decimal with at most 4 places."""
    sign = "-" if units < 0 else ""
    whole, fractional = divmod(abs(units), UNITS_PER_CURRENCY)
    if not fractional:
        return f"{sign}{whole}"
    fraction = f"{fractional:04d}".rstrip("0")
    return f"{sign}{whole}.{fraction}"


def format_currency_amount(units: int, currency: str) -> str:
    """Format an amount using the currency's minor units, rejecting excess precision."""
    precision = currency_precision(currency)
    unit_step = 10 ** (4 - precision)
    if units % unit_step:
        raise ValueError(
            f"{currency.upper()} amounts support at most {precision} decimal "
            "places."
        )
    sign = "-" if units < 0 else ""
    whole, fractional = divmod(abs(units), UNITS_PER_CURRENCY)
    if not precision:
        return f"{sign}{whole}"
    fraction = fractional // unit_step
    return f"{sign}{whole}.{fraction:0{precision}d}"
