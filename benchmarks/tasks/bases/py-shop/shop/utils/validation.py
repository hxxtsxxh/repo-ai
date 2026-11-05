"""Input validation helpers used by services and API handlers."""

import re

from shop.errors import ValidationError

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
SKU_RE = re.compile(r"^[A-Z]{3}-\d{4}$")
MAX_QUANTITY = 999


def is_valid_email(value) -> bool:
    return isinstance(value, str) and bool(EMAIL_RE.match(value.strip()))


def require_fields(data: dict, *fields: str) -> None:
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise ValidationError("missing required field(s): " + ", ".join(missing))


def validate_sku(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("sku must be a string")
    sku = value.strip().upper()
    if not SKU_RE.match(sku):
        raise ValidationError(f"invalid sku: {value!r}")
    return sku


def validate_quantity(value) -> int:
    if isinstance(value, bool):
        raise ValidationError("quantity must be an integer")
    try:
        qty = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("quantity must be an integer") from exc
    if qty < 1 or qty > MAX_QUANTITY:
        raise ValidationError(f"quantity must be between 1 and {MAX_QUANTITY}")
    return qty
