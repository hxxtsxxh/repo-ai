"""Loading the optional TOML configuration file.

Example::

    [logsift]
    ignore = ["healthcheck", "metrics"]
"""

import tomllib
from dataclasses import dataclass

from .errors import ConfigError

_KNOWN_KEYS = {"ignore"}


@dataclass(frozen=True)
class Config:
    ignore: tuple[str, ...] = ()


def load_config(path: str) -> Config:
    """Read the ``[logsift]`` table of a TOML file."""
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None

    table = data.get("logsift", {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: 'logsift' must be a table")
    for key in sorted(table):
        if key not in _KNOWN_KEYS:
            raise ConfigError(f"{path}: unknown setting '{key}'")

    ignore = table.get("ignore", [])
    if not isinstance(ignore, list) or not all(isinstance(item, str) for item in ignore):
        raise ConfigError(f"{path}: 'ignore' must be a list of strings")
    return Config(ignore=tuple(ignore))
