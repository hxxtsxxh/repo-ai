"""Validation helpers for unit quantities."""

from stockroom.errors import InvalidQuantityError


def require_positive_quantity(qty):
    """Return ``qty`` unchanged if it is a positive int, else raise.

    ``bool`` is rejected even though it is a subclass of ``int``.
    """
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise InvalidQuantityError(f"quantity must be a positive integer, got {qty!r}")
    return qty
