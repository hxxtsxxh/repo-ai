"""Human-readable byte sizes.

SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).
"""
import re
from fractions import Fraction

_UNITS = {"": 1, "B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3,
          "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3}
_SIZE = re.compile(r"([0-9]+(?:\.[0-9]+)?)( ?)([A-Za-z]*)\Z")


def parse_size(text):
    """Parse a size such as '10KB' or '1.5 KiB' into a whole number of bytes."""
    if not isinstance(text, str):
        raise TypeError("size must be a str")
    m = _SIZE.match(text)
    if m is None or (m.group(2) and not m.group(3)) or m.group(3).upper() not in _UNITS:
        raise ValueError(f"invalid size: {text!r}")
    value = Fraction(m.group(1)) * _UNITS[m.group(3).upper()]
    if value.denominator != 1:
        raise ValueError(f"not a whole number of bytes: {text!r}")
    return int(value)
