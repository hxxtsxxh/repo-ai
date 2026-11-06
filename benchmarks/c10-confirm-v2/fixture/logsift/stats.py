"""Counting records."""

import re
from collections import Counter
from collections.abc import Iterable

from .records import LogRecord

_DIGITS_RE = re.compile(r"\d+")


def sort_counts(counts: Counter[str]) -> list[tuple[str, int]]:
    """Order counted keys by count, highest first, then by key."""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def count_by(records: Iterable[LogRecord], field: str) -> list[tuple[str, int]]:
    """Count records by the value of one field, such as ``level`` or ``component``."""
    return sort_counts(Counter(getattr(record, field) for record in records))


def normalize_message(message: str) -> str:
    """Replace every run of digits with ``#`` so that similar messages group together."""
    return _DIGITS_RE.sub("#", message)


def top_messages(records: Iterable[LogRecord], limit: int) -> list[tuple[str, int]]:
    """Return the ``limit`` most frequent normalized messages."""
    counts = Counter(normalize_message(record.message) for record in records)
    return sort_counts(counts)[:limit]
