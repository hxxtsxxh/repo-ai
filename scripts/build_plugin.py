#!/usr/bin/env python3
"""Regenerate integrations/claude-plugin/ and .claude-plugin/marketplace.json.

    python scripts/build_plugin.py           # write
    python scripts/build_plugin.py --check   # exit 1 if the committed copy is stale
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from repo_ai.plugin import render_marketplace, render_plugin  # noqa: E402

PLUGIN_DIR = ROOT / "integrations" / "claude-plugin"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


def expected() -> dict[Path, str]:
    out = {PLUGIN_DIR / rel: body for rel, body in render_plugin().items()}
    out[MARKETPLACE] = render_marketplace()
    return out


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, body in expected().items():
        current = path.read_text("utf-8") if path.is_file() else None
        if current != body:
            stale.append(path.relative_to(ROOT).as_posix())
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
                if path.suffix == ".sh":
                    path.chmod(0o755)
    wanted = set(expected())
    for path in sorted(PLUGIN_DIR.rglob("*")) if PLUGIN_DIR.is_dir() else []:
        if path.is_file() and path not in wanted:
            stale.append(path.relative_to(ROOT).as_posix() + " (obsolete)")
            if not check:
                path.unlink()
    if check and stale:
        print("stale plugin files (run scripts/build_plugin.py):\n  " + "\n  ".join(stale))
        return 1
    print("plugin up to date" if not stale else f"wrote {len(stale)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
