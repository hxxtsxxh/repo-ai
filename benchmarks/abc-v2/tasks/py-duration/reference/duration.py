import re

UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_GRAMMAR = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?")


def parse_duration(text):
    stripped = text.strip()
    match = _GRAMMAR.fullmatch(stripped) if stripped.isascii() else None
    if not stripped or match is None:
        raise ValueError("invalid duration")
    return sum(int(n) * UNITS[u] for n, u in zip(match.groups(), "dhms") if n is not None)
