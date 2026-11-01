"""The git program to run.

On macOS, `/usr/bin/git` is Apple's launcher stub: on every call it asks xcrun
for the selected developer directory and then runs that directory's git. That
lookup costs about as much as the git command itself (measured on an Apple
Silicon Mac: 35 ms through the stub, 17 ms direct), and a verify run makes
about twenty git calls. `git()` resolves the stub to the same program
statically, the way xcrun selects it, without running xcrun or xcode-select:
`DEVELOPER_DIR` (an `.app` names its `Contents/Developer`), else the
`xcode-select` link, else the Command Line Tools. When anything is unusual
(another git first on PATH, a relative or missing selection, no git there),
it returns plain "git", which behaves exactly as before."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_APPLE_STUB = Path("/usr/bin/git")
_APPLE_DEVELOPER_LINK = Path("/private/var/db/xcode_select_link")
_APPLE_CLT_ROOT = Path("/Library/Developer/CommandLineTools")


def git() -> str:
    """argv[0] for a git command: "git", or on macOS the program Apple's stub would run."""
    if sys.platform != "darwin":
        return "git"
    try:
        found = shutil.which("git")
        if found is None or Path(found).resolve() != _APPLE_STUB.resolve():
            return "git"  # Homebrew's or another git comes first on PATH: PATH decides, as before
        selected = os.environ.get("DEVELOPER_DIR")
        if selected:
            developer = Path(selected)
            if not developer.is_absolute():
                return "git"
            if developer.suffix == ".app":
                developer = developer / "Contents" / "Developer"
        elif _APPLE_DEVELOPER_LINK.is_symlink() or _APPLE_DEVELOPER_LINK.exists():
            developer = _APPLE_DEVELOPER_LINK.resolve(strict=True)
        else:
            developer = _APPLE_CLT_ROOT
        target = (developer / "usr" / "bin" / "git").resolve(strict=True)
        if target == _APPLE_STUB.resolve() or not target.is_file() or not os.access(target, os.X_OK):
            return "git"
        return str(target)
    except (OSError, RuntimeError):
        return "git"
