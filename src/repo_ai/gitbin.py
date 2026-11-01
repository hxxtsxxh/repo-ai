"""The git program to run.

On macOS, `/usr/bin/git` is Apple's launcher stub: on every call it asks xcrun
for the selected developer directory and then runs that directory's git. That
lookup costs about as much as the git command itself (measured on an Apple
Silicon Mac: 35 ms through the stub, 17 ms direct), and a verify run makes
about twenty git calls. `git()` resolves the stub to the same program
once, with the same selection: `DEVELOPER_DIR` (an `.app` names its
`Contents/Developer`), else the `xcode-select` link, else what
`xcode-select -p` prints (xcode-select's own default search, asked once per
process rather than reproduced). Whenever anything is unusual (another git
first on PATH, a relative, missing or broken selection, no executable git
there), it returns plain "git", which behaves exactly as before."""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

_APPLE_STUB = Path("/usr/bin/git")
_APPLE_DEVELOPER_LINK = Path("/private/var/db/xcode_select_link")
_XCODE_SELECT = "/usr/bin/xcode-select"


@functools.lru_cache(maxsize=1)
def _default_developer() -> str | None:
    """xcode-select's answer when nothing is selected explicitly (its default search is undocumented)."""
    try:
        out = subprocess.run([_XCODE_SELECT, "-p"], capture_output=True, text=True, timeout=10, check=False,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    path = out.stdout.strip()
    return path if out.returncode == 0 and "\n" not in path and os.path.isabs(path) else None


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
            default = _default_developer()
            if default is None:
                return "git"
            developer = Path(default)
        target = (developer / "usr" / "bin" / "git").resolve(strict=True)
        if target == _APPLE_STUB.resolve() or not target.is_file() or not os.access(target, os.X_OK):
            return "git"
        return str(target)
    except (OSError, RuntimeError):
        return "git"
