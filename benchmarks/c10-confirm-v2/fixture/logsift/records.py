"""Reading log files into records.

A log line looks like::

    2026-03-04T10:15:00Z ERROR db: connection lost
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .errors import LogsiftError, ParseError

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_LINE_RE = re.compile(
    r"^(?P<time>\S+)\s+(?P<level>[A-Z]+)\s+(?P<component>[A-Za-z0-9_.-]+):\s?(?P<message>.*)$"
)


@dataclass(frozen=True)
class LogRecord:
    time: datetime
    level: str
    component: str
    message: str
    source: str
    lineno: int
    line: str


def level_rank(level: str) -> int:
    """Return the severity of a level name; higher is more severe."""
    return LEVELS.index(level)


def parse_line(line: str, source: str = "<string>", lineno: int = 1) -> LogRecord:
    """Parse one log line; the timestamp is converted to UTC."""
    match = _LINE_RE.match(line)
    if match is None or match["level"] not in LEVELS:
        raise ParseError(source, lineno, line)
    try:
        time = datetime.fromisoformat(match["time"])
    except ValueError:
        raise ParseError(source, lineno, line) from None
    if time.tzinfo is None:
        raise ParseError(source, lineno, line)
    return LogRecord(
        time=time.astimezone(timezone.utc),
        level=match["level"],
        component=match["component"],
        message=match["message"],
        source=source,
        lineno=lineno,
        line=line,
    )


def read_records(paths: list[str]) -> list[LogRecord]:
    """Read and parse every line of the given files, in the order given.

    Blank lines are ignored.
    """
    records: list[LogRecord] = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        except UnicodeDecodeError:
            raise LogsiftError(f"cannot read {path}: not valid UTF-8") from None
        except OSError as exc:
            raise LogsiftError(f"cannot read {path}: {exc.strerror}") from exc
        for lineno, line in enumerate(lines, start=1):
            if line.strip():
                records.append(parse_line(line, path, lineno))
    return records
