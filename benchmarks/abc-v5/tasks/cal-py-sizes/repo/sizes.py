"""Human-readable byte sizes.

SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).
"""
import re

_UNITS = {"": 1, "B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}
_SIZE = re.compile(r"(\d+)([A-Z]*)\Z")


def parse_size(text):
    """Parse a size such as '10KB' into a whole number of bytes."""
    if not isinstance(text, str):
        raise TypeError("size must be a str")
    m = _SIZE.match(text)
    if m is None or m.group(2) not in _UNITS:
        raise ValueError(f"invalid size: {text!r}")
    return int(m.group(1)) * _UNITS[m.group(2)]
