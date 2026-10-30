import re

UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    text = text.strip()
    parts = re.findall(r"(\d+)([dhms])", text)
    if not parts:
        raise ValueError("invalid duration")
    return sum(int(n) * UNITS[u] for n, u in parts)
