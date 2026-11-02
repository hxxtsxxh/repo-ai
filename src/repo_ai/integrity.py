"""Benchmark integrity: did an agent see hidden test material? (0.7.6)

Content similarity is not proof of leakage. A correct fix that updates an
existing test can reproduce the upstream (hidden) test exactly; Option A
invalidated five legitimate oss-tl-001 runs that way. So this module
separates three kinds of signal:

* **Proof of access** (invalidates the run):
  - a per-run canary token, planted in a decoy beside nothing the agent may
    read, turns up in the workspace or the transcript;
  - a tool call names protected material (the suite, the task's case
    directory, the lab) and its result was not a denial;
  - a tool result reveals a protected path, for example a `find` that
    listed the suite.
* **Attempts** (recorded, not invalidating): protected material named, but
  the access was denied by the sandbox or a permission rule.
* **Content diagnostics** (recorded, never invalidating on their own): a
  workspace file identical to a hidden test, and the share of hidden-only
  lines (lines in the hidden test but not in the visible version the agent
  started from) present in the agent's changes.

The OS sandbox and permission rules are the access control; this module is
the audit. A read through a channel that neither shows in the transcript nor
touches the canary can only surface as a content diagnostic, which is why
those are kept and reported.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import gitbin

_DENIAL = ("permission denied", "operation not permitted", "was denied", "has been denied",
           "access denied", "blocked by", "eacces", "eperm")


def protected_paths(*paths: Path) -> list[str]:
    """Absolute and home-relative spellings of the paths agents must not read."""
    home = str(Path.home())
    out: list[str] = []
    for p in paths:
        # native and POSIX spellings: transcripts name paths the way the tools do
        for s in {str(p), str(p.resolve()), p.as_posix(), p.resolve().as_posix()}:
            out.append(s)
            if s.startswith(home + "/"):
                out.append("~" + s[len(home):])
    return sorted(set(out), key=len, reverse=True)


def plant_canary(base: Path, task_id: str, names: list[str]) -> tuple[str, Path]:
    """A decoy hidden-test tree with a fresh token, under `base` (which every
    agent is denied). Shaped like a case directory, so a search for hidden
    tests that escapes the sandbox finds it."""
    token = f"REPO_AI_CANARY_{secrets.token_hex(12)}"
    root = base / "canaries" / secrets.token_hex(6)
    hidden = root / "cases" / task_id / "hidden"
    hidden.mkdir(parents=True, exist_ok=True)
    for name in names or ["test_hidden.py"]:
        (hidden / name).write_text(f"# {token}\n# decoy: reading this file is a protocol violation\n",
                                   encoding="utf-8")
    return token, root


def remove_canary(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def _events(lines: list[str]):
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(v.get("text", v.get("content", ""))) if isinstance(v, dict) else _text(v)
                         for v in value)
    if isinstance(value, dict):
        return json.dumps(value)
    return ""


def scan_transcript(lines: list[str], protected: list[str], canary: str) -> dict[str, Any]:
    """Tool calls and results that touch protected material, and the canary."""
    protected = [p.rstrip("/") for p in protected if p and len(p) > 4]
    calls: dict[str, tuple[str, str]] = {}
    access: list[str] = []
    attempts: list[str] = []
    canary_seen = False
    for event in _events(lines):
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        for block in message.get("content") or [] if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                arg = json.dumps(block.get("input") or {})
                calls[str(block.get("id", ""))] = (str(block.get("name", "")), arg)
                if canary and canary in arg:
                    canary_seen = True
            elif block.get("type") == "tool_result":
                name, arg = calls.get(str(block.get("tool_use_id", "")), ("", ""))
                body = _text(block.get("content"))
                if canary and canary in body:
                    canary_seen = True
                named = next((p for p in protected if p in arg), "")
                revealed = next((p for p in protected if p in body), "")
                denied = bool(block.get("is_error")) or any(d in body.lower() for d in _DENIAL)
                if named and denied:
                    attempts.append(f"{name or 'tool'} denied: {named}")
                elif named or revealed:
                    access.append(f"{name or 'tool'} {'read' if named else 'revealed'}: {named or revealed}")
            elif block.get("type") == "text" and canary and canary in str(block.get("text", "")):
                canary_seen = True
    return {"access": access[:20], "attempts": attempts[:20], "canary_seen": canary_seen}


def _git_show(ws: Path, rel: str, git_dir: Path | None = None) -> str:
    # the agent could write the workspace's .git: read the copy taken before the run when there is one, and never
    # run a configured command (fsmonitor, hooks, a promisor remote's lazy fetch)
    where = ["--git-dir", str(git_dir), "--work-tree", str(ws)] if git_dir is not None else []
    argv = [gitbin.git(), *where, "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
            "show", f"HEAD:{rel}"]
    try:
        out = subprocess.run(argv, cwd=ws, capture_output=True, text=True, check=False, timeout=30,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def content_diagnostics(hidden: list[tuple[str, bytes]], ws: Path, git_dir: Path | None = None) -> dict[str, Any]:
    """`hidden`: (workspace destination, hidden test bytes). Never proof."""
    identical: list[str] = []
    overlap_num = overlap_den = 0
    files = [p for p in ws.rglob("*") if p.is_file() and ".git" not in p.parts and not p.is_symlink()
             and p.stat().st_size < 2_000_000]
    blobs = {p.relative_to(ws).as_posix(): p.read_bytes() for p in files}
    corpus = "\n".join(b.decode("utf-8", "replace") for b in blobs.values())
    for dest, data in hidden:
        identical += [rel for rel, b in blobs.items() if b == data]
        visible = {line.strip() for line in _git_show(ws, dest, git_dir).splitlines()}
        only = [line.strip() for line in data.decode("utf-8", "replace").splitlines()
                if len(line.strip()) >= 8 and line.strip() not in visible]
        overlap_den += len(only)
        overlap_num += sum(1 for line in only if line in corpus)
    return {"identical_files": sorted(set(identical)),
            "hidden_only_lines": overlap_den,
            "hidden_only_lines_present": overlap_num}


def assess(lines: list[str], protected: list[str], canary: str, canary_root: Path | None,
           hidden: list[tuple[str, bytes]], ws: Path, git_dir: Path | None = None) -> dict[str, Any]:
    """The run's integrity verdict. `contaminated` lists proof only."""
    seen = scan_transcript(lines, protected, canary)
    if canary and not seen["canary_seen"]:
        for p in ws.rglob("*"):
            try:
                if p.is_file() and ".git" not in p.parts and canary.encode() in p.read_bytes():
                    seen["canary_seen"] = True
                    break
            except OSError:
                continue
    proof = list(seen["access"]) + (["canary token found (a protected decoy was read)"]
                                    if seen["canary_seen"] else [])
    return {"contaminated": proof, "hidden_access_attempts": seen["attempts"],
            "hidden_content_match": content_diagnostics(hidden, ws, git_dir)}
