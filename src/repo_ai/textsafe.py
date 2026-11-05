"""Display text taken from untrusted sources: third-party skills, plugins, repositories, tool output.

Anything a repository controls (names, descriptions, file names, commands, findings' evidence) can carry
terminal escape sequences, bidi overrides, zero-width characters or newlines. Printed raw, they can
clear the screen, forge a "clean" line, or reorder what a person (or an agent reading the output)
sees. `display()` makes such text inert: controls and invisible characters become visible escapes, and
the result is one line. JSON output does not need this: `json.dumps` already escapes controls.
"""

from __future__ import annotations

import re
import shlex

# C0/C1 controls (newline and tab included), DEL, bidi controls, zero-width and other invisible characters
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f؜᠎​-‏ -‮⁠-⁩﻿"
                     "\U000e0000-\U000e007f]")
_SIMPLE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")


def display(text: object, limit: int = 200) -> str:
    """One inert line: every control or invisible character shown as an escape, truncated to `limit`."""
    s = _UNSAFE.sub(lambda m: m.group(0).encode("unicode_escape").decode("ascii"), str(text))
    return s if len(s) <= limit else s[: max(0, limit - 1)] + "…"


def shell_word(text: str) -> str:
    """A word that can be pasted into a shell command: simple names as they are, anything else quoted."""
    return text if _SIMPLE_NAME.match(text) else shlex.quote(display(text, 120))
