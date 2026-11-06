#!/usr/bin/env python3
"""Record the terminal transcripts the website shows, from a real run of a repo-ai executable.

The landing page's walkthrough (``site/src/data/transcripts.ts``) and the quickstart page
(``site/src/content/docs/quickstart.md``) show repo-ai output that must be real. This script produces that output:

1. copies ``tests/fixtures/pyweb`` into a fresh temporary directory (``…/demo``), git-inits it with a fixed identity
   (``demo@example.invalid``) and a fixed date, and commits it;
2. points ``HOME`` and ``REPO_AI_HOME`` at directories inside the same temporary area (shown as ``~``) and sets
   ``REPO_AI_NO_BACKGROUND=1``, so neither the real home nor any real repository is read or written;
3. runs the command sequence the two pages show, with the one edit they verify (``email = (email or "").strip()``
   at the top of ``validate_credentials`` in ``app/auth/login.py``) between ``impact`` and ``verify``;
4. writes one JSON object per step: argv, exit code, duration and the combined stdout+stderr, with the temporary
   paths shortened to ``…/demo`` and ``~``.

    PATH=/path/to/testenv/bin:$PATH \
        python scripts/record_transcripts.py --repo-ai /path/to/venv/bin/repo-ai --out transcripts.jsonl

`verify --run` runs the demo's tests with the `python` found on PATH, which needs pytest and PyJWT (the fixture's
`app/auth/tokens.py` imports `jwt`); without them the tests fail at the base too and the run reports that. The first
JSON line records the repo-ai version and that interpreter.

Only repo-ai commands run on the fixture (plus the git calls that create it). Nothing touches the network beyond
what repo-ai itself does offline. The temporary area is removed afterwards unless ``--keep`` is given."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pyweb"

EDIT_FILE = "app/auth/login.py"
EDIT_AFTER = '    """Check the email/password pair against the stored hash."""\n'
EDIT_LINE = '    email = (email or "").strip()\n'

# The quickstart page's sequence plus the landing page's extra commands. `do --dry-run` (which writes nothing) and
# `agents list` run before the edit: `do` plans on a clean checkout, as a mission would start.
STEPS: list[tuple[str, ...]] = [
    ("init", "--agent", "none"),
    ("context", "fix the login validation bug"),
    ("impact", EDIT_FILE),
    ("do", "Reject emails with surrounding whitespace in login validation", "--dry-run"),
    ("agents", "list"),
    ("@edit",),
    ("verify",),
    ("verify", "--run"),
    ("evidence",),
    ("review", "--changed"),
    ("privacy", "audit"),
    ("uninstall", "--dry-run"),
]

GIT_ID = {"GIT_AUTHOR_NAME": "repo-ai demo", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
          "GIT_COMMITTER_NAME": "repo-ai demo", "GIT_COMMITTER_EMAIL": "demo@example.invalid",
          "GIT_AUTHOR_DATE": "2026-01-01T12:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T12:00:00+0000"}


def _variants(path: Path) -> list[str]:
    """The spellings of `path` that output may contain (macOS: /var and /private/var), longest first."""
    seen = {str(path), os.path.realpath(path)}
    for s in list(seen):
        if s.startswith("/private/"):
            seen.add(s[len("/private"):])
        elif s.startswith(("/var/", "/tmp/")):
            seen.add("/private" + s)
    return sorted(seen, key=len, reverse=True)


class Redactor:
    def __init__(self, demo: Path, home: Path, area: Path):
        self.rules: list[tuple[str, str]] = []
        for path, short in ((demo, "…/demo"), (home, "~"), (area, "…")):
            self.rules += [(v, short) for v in _variants(path)]
        ws = Path(tempfile.gettempdir()) / f"repo-ai-ws-{os.getuid()}"
        self.rules += [(v, "…/repo-ai-ws") for v in _variants(ws)]
        self.rules += [(v, "…") for v in _variants(Path(tempfile.gettempdir()))]
        self.real_home = os.path.realpath(Path.home())

    def __call__(self, text: str) -> str:
        for long, short in self.rules:
            text = text.replace(long, short)
        return text

    def leaks_real_home(self, text: str) -> bool:
        return self.real_home not in ("/", "") and self.real_home in text


def make_demo(area: Path) -> Path:
    demo = area / "demo"
    shutil.copytree(FIXTURE, demo)
    env = {**_base_env(area / "home"), **GIT_ID}
    for argv in (["git", "init", "-q", "-b", "main"], ["git", "add", "-A"],
                 ["git", "commit", "-q", "-m", "demo: initial commit"]):
        subprocess.run(argv, cwd=demo, env=env, check=True, capture_output=True)
    return demo


def _base_env(home: Path) -> dict[str, str]:
    """The inherited environment minus anything repo-ai or Python would read from elsewhere, with a temp HOME."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("REPO_AI_", "PYTHON", "VIRTUAL_ENV", "GIT_", "XDG_"))}
    env.update({"HOME": str(home), "REPO_AI_HOME": str(home / ".repo-ai"), "REPO_AI_NO_BACKGROUND": "1",
                "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local" / "share"), "XDG_STATE_HOME": str(home / ".local" / "state"),
                "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _check_isolated(env: dict[str, str], area: Path, demo: Path) -> None:
    """Refuse to run anything unless HOME, REPO_AI_HOME and the working directory are inside the temp area."""
    real_area = os.path.realpath(area)
    real_home = os.path.realpath(Path.home())
    for name in ("HOME", "REPO_AI_HOME"):
        value = os.path.realpath(env.get(name, ""))
        if not value.startswith(real_area + os.sep) or value == real_home:
            raise SystemExit(f"refusing to run: {name}={env.get(name)!r} is not inside the temporary area")
    real_demo = os.path.realpath(demo)
    if not real_demo.startswith(real_area + os.sep) or real_demo.startswith(os.path.realpath(ROOT) + os.sep):
        raise SystemExit(f"refusing to run: {demo} is not a temporary copy")


def _python_version(python: str | None, env: dict[str, str]) -> str:
    if not python:
        return "none"
    code = ("import sys\nfrom importlib.metadata import version as v\n"
            "def get(n):\n    try: return v(n)\n    except Exception: return 'absent'\n"
            "print(sys.version.split()[0], 'pytest', get('pytest'), 'PyJWT', get('PyJWT'))")
    return subprocess.run([python, "-I", "-c", code], env=env, capture_output=True, text=True,
                          timeout=60).stdout.strip()


def apply_edit(demo: Path) -> None:
    path = demo / EDIT_FILE
    text = path.read_text()
    if text.count(EDIT_AFTER) != 1:
        raise SystemExit(f"{EDIT_FILE}: cannot find where the edit goes")
    path.write_text(text.replace(EDIT_AFTER, EDIT_AFTER + EDIT_LINE))


def record(repo_ai: Path, out: Path, keep: bool) -> int:
    area = Path(tempfile.mkdtemp(prefix="repo-ai-transcripts-"))
    home = area / "home"
    (home / ".repo-ai").mkdir(parents=True)
    env = _base_env(home)
    try:
        demo = make_demo(area)
        _check_isolated(env, area, demo)
        redact = Redactor(demo, home, area)
        version = subprocess.run([str(repo_ai), "--version"], cwd=demo, env=env, stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=60).stdout.strip()
        # the interpreter the demo's tests run under (`python` on PATH), shown without its directory
        test_python = shutil.which("python", path=env.get("PATH"))
        shown_python = "…/" + "/".join(Path(test_python).parts[-2:]) if test_python else "none"
        records: list[dict] = [{"meta": {
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "platform": platform.platform(terse=True),
            "repo_ai": version, "fixture": "tests/fixtures/pyweb",
            "test_python": shown_python, "test_python_version": _python_version(test_python, env),
        }}]
        leaked = []
        for step in STEPS:
            if step == ("@edit",):
                apply_edit(demo)
                records.append({"edit": EDIT_FILE, "inserted": EDIT_LINE.rstrip("\n"),
                                "after": EDIT_AFTER.rstrip("\n")})
                continue
            _check_isolated(env, area, demo)
            start = time.monotonic()
            proc = subprocess.run([str(repo_ai), *step], cwd=demo, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
            duration = round(time.monotonic() - start, 2)
            text = proc.stdout.decode("utf-8", "replace")
            if redact.leaks_real_home(text):
                leaked.append(" ".join(step))
            records.append({"argv": ["repo-ai", *step], "exit": proc.returncode, "duration_s": duration,
                            "output": redact(text)})
            print(f"exit {proc.returncode:>3}  {duration:6.2f}s  repo-ai {' '.join(step)}", file=sys.stderr)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if leaked:
            print(f"warning: the real home directory appears in the output of: {', '.join(leaked)}", file=sys.stderr)
        return 0
    finally:
        if keep:
            print(f"kept {area}", file=sys.stderr)
        else:
            shutil.rmtree(area, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo-ai", required=True, type=Path, help="the repo-ai executable to record")
    ap.add_argument("--out", required=True, type=Path, help="where to write the JSON lines")
    ap.add_argument("--keep", action="store_true", help="keep the temporary area (prints its path)")
    args = ap.parse_args(argv)
    exe = args.repo_ai.expanduser().absolute()
    if not (exe.is_file() and os.access(exe, os.X_OK)):
        ap.error(f"--repo-ai {args.repo_ai}: not an executable file")
    return record(exe, args.out.expanduser().absolute(), args.keep)


if __name__ == "__main__":
    sys.exit(main())
