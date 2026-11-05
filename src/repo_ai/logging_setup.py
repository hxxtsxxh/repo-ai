"""Logging. Human output goes to stderr so stdout stays machine-parseable.

This matters: `repo-ai context "..."` is designed to be piped straight into a
Bob lifecycle hook, so stdout must contain only the payload.
"""

from __future__ import annotations

import logging
import sys
import time

_LEVEL_COLORS = {
    "DEBUG": "\033[90m",
    "INFO": "\033[36m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m",
}
_RESET = "\033[0m"


class _Formatter(logging.Formatter):
    def __init__(self, color: bool) -> None:
        super().__init__("%(message)s")
        self.color = color
        self.start = time.monotonic()

    def format(self, record: logging.LogRecord) -> str:
        elapsed = time.monotonic() - self.start
        prefix = f"[{elapsed:6.2f}s] "
        msg = record.getMessage()
        if record.levelno >= logging.WARNING:
            label = record.levelname.lower()
            msg = f"{label}: {msg}"
        if self.color:
            col = _LEVEL_COLORS.get(record.levelname, "")
            return f"\033[90m{prefix}{_RESET}{col}{msg}{_RESET}"
        return prefix + msg


def setup_logging(verbose: bool = False, quiet: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    logger = logging.getLogger("repo_ai")
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_Formatter(color=sys.stderr.isatty()))
    handler.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("repo_ai")
