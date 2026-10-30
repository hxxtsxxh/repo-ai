from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from invoicekit.errors import InvoiceError


def parse_amount(text):
    """Parse a decimal string such as "12.34" into integer cents."""
    try:
        value = Decimal(str(text).strip())
    except InvalidOperation:
        raise InvoiceError(f"not an amount: {text!r}") from None
    if not value.is_finite():
        raise InvoiceError(f"not an amount: {text!r}")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def format_amount(cents, currency):
    """Render integer cents with an ISO 4217 code, e.g. "USD 12.34"."""
    code = str(currency).strip()
    if len(code) != 3 or not code.isalpha():
        raise InvoiceError(f"bad currency code: {currency!r}")
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    return f"{code.upper()} {sign}{whole}.{frac:02d}"
