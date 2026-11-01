"""SKU parsing and normalisation."""

import re

from stockroom.errors import InvalidSkuError

_SKU_PATTERN = re.compile(r"[A-Z]{3}-\d{4}")


def normalize_sku(raw):
    """Return the canonical form of ``raw``: stripped and upper-cased.

    Raises InvalidSkuError if the result is not three letters, a hyphen
    and four digits (for example ``"BLT-0042"``).
    """
    if not isinstance(raw, str):
        raise InvalidSkuError(f"invalid SKU: {raw!r}")
    sku = raw.strip().upper()
    if not _SKU_PATTERN.fullmatch(sku):
        raise InvalidSkuError(f"invalid SKU: {raw!r}")
    return sku
