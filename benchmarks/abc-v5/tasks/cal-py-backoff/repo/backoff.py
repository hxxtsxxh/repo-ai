"""Retry delay schedule.

SYNTHETIC calibration module written for repo-ai benchmark abc-v5 (not upstream code).
"""


def delays(attempts, base=1.0, factor=2.0, cap=60.0):
    """Return the delay in seconds to wait before each of ``attempts`` retries."""
    return [base * factor ** i for i in range(attempts)]
