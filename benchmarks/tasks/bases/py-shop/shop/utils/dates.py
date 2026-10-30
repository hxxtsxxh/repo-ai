"""Date helpers. Delivery maths only ever counts Monday-Friday."""

from datetime import date, datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"not an ISO date: {value!r}") from exc


def is_business_day(day: date) -> bool:
    return day.weekday() < 5


def add_business_days(start: date, days: int) -> date:
    """Return the date ``days`` business days after ``start``.

    ``start`` itself is never counted, so ``add_business_days(friday, 1)``
    is the following Monday.
    """
    if days < 0:
        raise ValueError("days must be non-negative")
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def format_date(day: date) -> str:
    """``date(2026, 3, 4)`` -> ``"Wed, Mar 04 2026"``."""
    return day.strftime("%a, %b %d %Y")


def isoformat(moment) -> str:
    return moment.isoformat() if moment is not None else None
