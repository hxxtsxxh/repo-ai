import re

UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    return sum(int(n) * UNITS[u] for n, u in re.findall(r"(\d+)([dhms])", text))
