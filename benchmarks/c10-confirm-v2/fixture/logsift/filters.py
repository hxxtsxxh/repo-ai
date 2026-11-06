"""Selecting records."""

from collections.abc import Iterable

from .records import LogRecord, level_rank


def filter_records(
    records: Iterable[LogRecord],
    *,
    min_level: str | None = None,
    components: Iterable[str] = (),
    text: str | None = None,
    ignore: Iterable[str] = (),
) -> list[LogRecord]:
    """Return the records that pass every given condition, in their original order.

    ``components`` keeps only the named components (all when empty), ``ignore``
    drops the named components, and ``text`` keeps messages containing it.
    """
    wanted = set(components)
    ignored = set(ignore)
    threshold = level_rank(min_level) if min_level is not None else 0
    selected = []
    for record in records:
        if level_rank(record.level) < threshold:
            continue
        if wanted and record.component not in wanted:
            continue
        if record.component in ignored:
            continue
        if text is not None and text not in record.message:
            continue
        selected.append(record)
    return selected
