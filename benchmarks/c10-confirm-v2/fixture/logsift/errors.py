"""Exceptions raised by logsift functions."""


class LogsiftError(Exception):
    """An error that is reported to the user as a failed command."""


class ParseError(LogsiftError):
    """A log line does not have the expected layout."""

    def __init__(self, path: str, lineno: int, line: str) -> None:
        super().__init__(f"cannot parse {path} line {lineno}: {line!r}")
        self.path = path
        self.lineno = lineno
        self.line = line


class ConfigError(LogsiftError):
    """The configuration file is missing, malformed or has bad values."""


class OutputExistsError(LogsiftError):
    """The output file already exists and may not be replaced."""

    def __init__(self, path: str) -> None:
        super().__init__(f"{path} already exists (use --force to overwrite)")
        self.path = path
