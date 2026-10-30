"""Retry delay schedule.

SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).
"""


def delays(attempts, base=1.0, factor=2.0, cap=60.0):
    """Return the delay in seconds to wait before each of ``attempts`` retries."""
    if not isinstance(attempts, int):
        raise TypeError("attempts must be an int")
    if attempts < 0:
        raise ValueError("attempts must be >= 0")
    if not base > 0 or not factor >= 1 or not cap >= base:
        raise ValueError("need base > 0, factor >= 1 and cap >= base")
    return [min(base * factor ** i, cap) for i in range(attempts)]
