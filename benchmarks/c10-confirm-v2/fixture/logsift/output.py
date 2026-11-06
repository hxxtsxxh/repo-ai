"""Writing output files."""

import json
from collections.abc import Iterable
from pathlib import Path

from .errors import LogsiftError, OutputExistsError
from .records import LogRecord


def write_text(path: str, text: str, *, force: bool = False) -> None:
    """Write text to a file as UTF-8 with ``\\n`` line endings.

    An existing file is only replaced when ``force`` is true.
    """
    target = Path(path)
    if target.exists() and not force:
        raise OutputExistsError(path)
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        raise LogsiftError(f"cannot write {path}: {exc.strerror}") from exc


def record_to_object(record: LogRecord) -> dict[str, object]:
    return {
        "component": record.component,
        "level": record.level,
        "lineno": record.lineno,
        "message": record.message,
        "source": record.source,
        "time": record.time.isoformat(),
    }


def records_to_jsonl(records: Iterable[LogRecord]) -> str:
    """Return one compact JSON object per record, one per line."""
    return "".join(
        json.dumps(record_to_object(record), sort_keys=True, ensure_ascii=False) + "\n"
        for record in records
    )
