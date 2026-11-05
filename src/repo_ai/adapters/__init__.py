"""Agent adapters. One canonical engine; per-agent file formats live here."""

from __future__ import annotations

from .base import Adapter, Check, SetupContext
from .bob import BobAdapter
from .claude import ClaudeAdapter

ADAPTERS: dict[str, Adapter] = {"bob": BobAdapter(), "claude": ClaudeAdapter()}

# Bob runs first: `claude_reads_agents_md` decides deduplication up front, so
# order does not change output, but a stable order keeps plans readable.
ORDER = ("bob", "claude")


def ordered(agents) -> list[str]:
    return [a for a in ORDER if a in set(agents)]


__all__ = ["ADAPTERS", "Adapter", "Check", "SetupContext", "ordered"]
