"""Money helpers.

All amounts inside the shop are integer cents. Conversions to and from
user-facing strings happen only at the edges (API input, serializers,
notification bodies) and always round half-up to the nearest cent.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}

_ONE = Decimal("1")
_HUNDREDTH = Decimal("0.01")


def to_cents(value) -> int:
    """Parse ``"12.34"`` / ``Decimal("12.34")`` / ``12`` (dollars) into cents."""
    if isinstance(value, bool):
        raise TypeError("amount must be a number or numeric string")
    if isinstance(value, float):
        value = repr(value)
    try:
        dec = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    if not dec.is_finite():
        raise ValueError(f"invalid amount: {value!r}")
    return int((dec * 100).quantize(_ONE, rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> Decimal:
    """Return a two-decimal ``Decimal`` for an integer number of cents."""
    return (Decimal(cents) / 100).quantize(_HUNDREDTH)


def format_money(cents: int, currency: str = "USD") -> str:
    """Human-readable amount, e.g. ``format_money(-123456) == "-$1,234.56"``."""
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    return f"{sign}{symbol}{whole:,}.{frac:02d}"


def apply_percent(cents: int, percent) -> int:
    """Return ``percent`` % of ``cents`` rounded half-up to a whole cent."""
    share = (Decimal(cents) * Decimal(str(percent)) / 100).quantize(
        _ONE, rounding=ROUND_HALF_UP
    )
    return int(share)


def apply_basis_points(cents: int, basis_points: int) -> int:
    """Return ``cents * bp / 10000`` rounded half-up (used for tax)."""
    raw = Decimal(cents) * Decimal(basis_points) / Decimal(10_000)
    return int(raw.quantize(_ONE, rounding=ROUND_HALF_UP))


def allocate(cents: int, weights: list) -> list:
    """Split ``cents`` proportionally to ``weights``.

    The parts always sum to ``cents``; leftover cents go to the earliest
    shares so the result is deterministic.
    """
    if not weights:
        return []
    total_weight = sum(weights)
    if total_weight <= 0:
        raise ValueError("weights must sum to a positive number")
    parts = [cents * w // total_weight for w in weights]
    remainder = cents - sum(parts)
    for i in range(remainder):
        parts[i % len(parts)] += 1
    return parts
