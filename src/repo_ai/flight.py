"""Context Flight Recorder: opt-in, local, prompt-free hook diagnostics.

When `flight_recorder = true` (or `REPO_AI_FLIGHT_RECORDER=1` for one
session), each prompt-hook decision is appended to `state/flight.jsonl`:
what was injected or omitted and why, the ranked candidates, confidence,
timings and a token *estimate*. The prompt itself is never stored, only a
short hash and its length. `repo-ai debug last` reads it, and
`repo-ai debug purge` deletes it. The file is capped at the most recent
entries and lives in the machine-local state directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

MAX_ENTRIES = 200


def path_for(layout) -> Path:
    return layout.state_dir / "flight.jsonl"


def prompt_fingerprint(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()[:12]


def record(layout, cfg, entry: dict[str, Any]) -> None:
    if not getattr(cfg, "flight_recorder", False):
        return
    path = path_for(layout)
    entry = {"ts": round(time.time(), 3), **entry}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, (json.dumps(entry, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        if path.stat().st_size > 512 * 1024:
            _truncate(path)
    except OSError:
        pass  # diagnostics never break a hook


def _truncate(path: Path) -> None:
    lines = path.read_text("utf-8", errors="replace").splitlines()[-MAX_ENTRIES:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def entries(layout, limit: int = 1) -> list[dict[str, Any]]:
    try:
        lines = path_for(layout).read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-max(limit, 1):]:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):  # anything else is not a record repo-ai wrote
            clean = _coerce(item)
            if clean is not None:
                out.append(clean)
    return out


def _coerce(item: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only well-typed fields; a hand-edited or committed log must not
    crash `debug`/`budget`."""
    def num(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    out: dict[str, Any] = {k: v for k, v in item.items() if isinstance(v, str) and len(v) < 200
                           and k in {"event", "prompt_sha", "confidence", "decision", "reason"}}
    for key in ("ts", "prompt_chars", "tokens_est", "elapsed_ms", "index_age_s"):
        value = num(item.get(key))
        if value is not None:
            out[key] = value
    out["cache_hit"] = bool(item.get("cache_hit") is True)
    out["intents"] = [i for i in item.get("intents") or [] if isinstance(i, str)][:6] \
        if isinstance(item.get("intents"), list) else []
    out["injected"] = [p for p in item.get("injected") or [] if isinstance(p, str)][:20] \
        if isinstance(item.get("injected"), list) else []
    raw_cands = item.get("candidates")
    cands: list[Any] = raw_cands if isinstance(raw_cands, list) else []
    out["candidates"] = [{"path": c["path"], "score": float(c.get("score", 0) or 0)}
                         for c in cands if isinstance(c, dict) and isinstance(c.get("path"), str)
                         and isinstance(c.get("score", 0), (int, float))][:20]
    return out if out.get("event") else None


def purge(layout) -> bool:
    try:
        path_for(layout).unlink()
        return True
    except FileNotFoundError:
        return False


def render(entry: dict[str, Any]) -> str:
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("ts", 0)))
    lines = [f"{when}  {entry.get('event', '?')}  prompt #{entry.get('prompt_sha', '-')} "
             f"({entry.get('prompt_chars', 0)} chars)",
             f"  decision: {entry.get('decision', '?')}"
             + (f" — {entry['reason']}" if entry.get("reason") else ""),
             f"  confidence: {entry.get('confidence', '-')}  intents: "
             f"{', '.join(entry.get('intents', [])) or '-'}  cache: "
             f"{'hit' if entry.get('cache_hit') else 'miss'}  index age: "
             f"{entry.get('index_age_s', '?')} s  elapsed: {entry.get('elapsed_ms', '?')} ms"]
    if entry.get("injected"):
        lines.append(f"  injected ({entry.get('tokens_est', 0)} tokens, estimate):")
        lines += [f"    {p}" for p in entry["injected"]]
    candidates = entry.get("candidates") or []
    if candidates:
        lines.append("  ranked candidates:")
        injected = set(entry.get("injected") or [])
        for c in candidates:
            mark = "+" if c.get("path") in injected else " "
            lines.append(f"   {mark} {c.get('score', 0):6.2f}  {c.get('path')}")
    return "\n".join(lines)
