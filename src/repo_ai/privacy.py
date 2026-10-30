"""`repo-ai privacy audit`: what repo-ai stores, where, and whether it should.

The four stores (docs/LEARNING.md):

1. **Project facts**: deterministic analysis of the repository (the index
   and the generated docs). They contain code-derived facts, and the docs are
   committed by default.
2. **Episodic outcomes**: opt-in, machine-local. Edited paths, known-command
   results and session status; never prompts or output.
3. **Candidate rules and skills**: the learning ledger, history and
   snapshots. Committed by default, because they are reviewable project
   policy.
4. **Portable patterns**: opt-in cross-repository library, per zone
   (`registry.py`). Lives outside every repository.

Plus the support stores: signals, the flight recorder, the ownership ledger
of original file bytes, backups, `repo-ai verify`'s records (evidence with
the last lines of failing test output, the test map, baseline, timings and
scan cache), and, outside the repository (`registry.machine_dir`), the
capability approvals and run logs.

The audit verifies each local store against an allow-list of fields and
flags anything that looks like free text (a possible prompt or output leak).
It exits non-zero on a violation.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FREE_TEXT_LIMIT = 160  # a string longer than this in an outcome store is suspicious


@dataclass(slots=True)
class Store:
    name: str
    kind: str  # facts | outcomes | candidates | patterns | support | disclosure
    path: str
    exists: bool
    bytes: int
    entries: int | None
    contains: str
    retention: str
    committed: str  # yes | no (gitignored) | untracked | n/a
    problems: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _size(path: Path) -> tuple[int, int | None]:
    if path.is_file():
        try:
            return path.stat().st_size, None
        except OSError:
            return 0, None
    if path.is_dir():
        total, count = 0, 0
        for p in path.rglob("*"):
            try:                      # another process may delete a file between the walk and the stat
                if p.is_file():
                    total += p.stat().st_size
                    count += 1
            except OSError:
                continue
        return total, count
    return 0, None


def _git_state(root: Path, rel: str) -> str:
    try:
        tracked = subprocess.run(["git", "ls-files", "--", rel], cwd=root, capture_output=True,
                                 text=True, timeout=10, check=False)
        if tracked.returncode != 0:
            return "n/a"
        if tracked.stdout.strip():
            return "yes"
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=root,
                                 capture_output=True, timeout=10, check=False)
        return "no (gitignored)" if ignored.returncode == 0 else "untracked"
    except (OSError, subprocess.SubprocessError):
        return "n/a"


def _check_jsonl_keys(path: Path, allowed: set[str], text_ok: set[str]) -> tuple[int, list[str]]:
    problems: list[str] = []
    n = 0
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return 0, []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            problems.append("unparseable line")
            continue
        n += 1
        if not isinstance(item, dict):
            problems.append("line is not a JSON object")
            continue
        extra = {str(k) for k in item} - allowed
        if extra:
            problems.append(f"unexpected field(s) {sorted(extra)}")
        for key, value in item.items():
            if key not in text_ok and isinstance(value, str) and len(value) > FREE_TEXT_LIMIT:
                problems.append(f"long free text in `{key}`")
    return n, sorted(set(problems))


def _check_episodes(directory: Path) -> tuple[int, list[str]]:
    from .episodes import ALLOWED_KEYS, ALLOWED_PROMPT_KEYS
    problems: list[str] = []
    n = 0
    for path in sorted(directory.glob("*.json")):
        n += 1
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            problems.append(f"{path.name}: unreadable")
            continue
        extra = set(data) - ALLOWED_KEYS
        if extra:
            problems.append(f"{path.name}: unexpected field(s) {sorted(extra)}")
        for prompt in data.get("prompts") or []:
            extra = set(prompt) - ALLOWED_PROMPT_KEYS
            if extra:
                problems.append(f"{path.name}: prompt record has {sorted(extra)}")
        blob = json.dumps(data)
        for value in _strings(data):
            if len(value) > FREE_TEXT_LIMIT:
                problems.append(f"{path.name}: long free text ({len(value)} chars)")
                break
        if len(blob) > 200_000:
            problems.append(f"{path.name}: unexpectedly large")
    return n, sorted(set(problems))


def _check_query_cache(db: Path) -> tuple[int, list[str]]:
    """The query cache is keyed by a hash; its payloads must hold no prompt text."""
    import sqlite3
    import zlib
    if not db.is_file():
        return 0, []
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        rows = conn.execute("SELECT payload FROM query_cache").fetchall()
        conn.close()
    except sqlite3.Error:
        return 0, []
    problems = []
    for (blob,) in rows:
        try:
            data = json.loads(zlib.decompress(blob).decode("utf-8"))
        except (zlib.error, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and ("query" in data or data.get("v") != 2):
            problems.append("query cache holds prompt-derived text (pre-0.6 entries; "
                            "`repo-ai update` clears them)")
            break
    return len(rows), problems


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def audit(root: Path, cfg, layout) -> list[Store]:
    from .registry import registry_home

    stores: list[Store] = []

    def add(name: str, kind: str, path: Path, contains: str, retention: str,
            entries: int | None = None, problems: list[str] | None = None) -> None:
        size, count = _size(path)
        try:
            rel = path.relative_to(root).as_posix()
            committed = _git_state(root, rel) if path.exists() else "n/a"
        except ValueError:
            rel, committed = str(path), "outside repository"
        stores.append(Store(name, kind, rel, path.exists(), size,
                            entries if entries is not None else count, contains, retention,
                            committed, problems or []))

    n, problems = _check_query_cache(layout.index_path)
    add("index", "facts", layout.index_path, "code-derived facts: paths, symbols, imports, routes, "
        "search text of indexed files (quarantined secret files excluded); query cache of "
        "ranked results keyed by prompt hash", "rebuilt on update", None, problems)
    add("generated docs", "facts", layout.context_dir, "Markdown summaries and facts.json",
        "rewritten on update")
    add("learning ledger", "candidates", layout.learning_dir, "rules with evidence pointers, "
        "history, file snapshots for rollback", "40 snapshots")
    n, problems = _check_jsonl_keys(layout.signals_path,
                                    {"ts", "event", "key", "session", "kind"}, {"key"})
    add("signals", "outcomes", layout.signals_path, "known-command names, task classes, hashed "
        "session ids", "last 1000 events, 60 days", n, problems)
    ep_dir = layout.state_dir / "episodes"
    n, problems = _check_episodes(ep_dir) if ep_dir.is_dir() else (0, [])
    add("episodes", "outcomes", ep_dir, "per session: task classes, candidate/injected/edited "
        "paths, known-command results, status (no prompts, no output)", "30 days, 400 sessions",
        n, problems)
    from .flight import path_for
    n, problems = _check_jsonl_keys(path_for(layout), {
        "ts", "event", "prompt_sha", "prompt_chars", "confidence", "intents", "cache_hit",
        "index_age_s", "candidates", "decision", "reason", "injected", "tokens_est",
        "elapsed_ms"}, set())
    add("flight recorder", "support", path_for(layout), "hook decisions: hashed prompt, "
        "candidates, timings (opt-in)", "last 200 entries", n, problems)
    add("outcome prior", "outcomes", layout.state_dir / "ranking.json", "promoted per-file "
        "ranking weights and their shadow evaluation", "until rolled back")
    add("ownership ledger", "support", layout.originals_path, "pre-install bytes of human files "
        "repo-ai edited (CLAUDE.md, settings.json, .gitignore...) for exact uninstall",
        "until uninstall")
    add("backups", "support", layout.backup_dir, "copies of files before each repo-ai write",
        "last 8 writes")
    # `repo-ai verify`: runtime records and caches, all machine-local (gitignored)
    add("verification evidence", "support", layout.state_dir / "evidence", "per verify run: "
        "changed paths, selected tests, commands and results, and the last lines of failing "
        "test output (secret-shaped values scrubbed); static-security capability evidence",
        "last 50 runs")
    add("missions (experimental)", "support", layout.state_dir / "missions",
        "local task contracts and task text, provider/replay identity, candidate diffs, bounded test evidence, "
        "event metadata, redacted diagnostic summaries, source hashes and checkpoints; "
        "task text is redacted and source diffs reject recognized secret-shaped material",
        "64 missions maximum; until explicit removal or uninstall")
    add("test map", "support", layout.state_dir / "testmap.json", "runtime evidence: which "
        "code objects each test file executed (`repo-ai verify --record`)", "until re-recorded")
    add("verify baseline", "support", layout.state_dir / "verify-baseline.json", "pass/fail "
        "outcomes and failing test ids at a base tree, keyed by hashes of the environment",
        "20000 entries")
    add("verify timings", "support", layout.state_dir / "verify-timings.json", "measured wall "
        "times (full suite, each test file, sandbox start-up) per environment", "8 environments")
    add("verify scan cache", "support", layout.state_dir / "verify-scan-cache.json", "per Python "
        "file: dynamic-loader and string-reference scan results, keyed by size and mtime",
        "rebuilt as files change")
    add("completion gate", "support", layout.state_dir / "gate.json", "the change fingerprints the Stop-hook "
        "gate already reported on, per session (hashes only)", "per session")
    add("ProofLab (experimental)", "support", layout.state_dir / "prove", "pinned claims: the claim text you "
        "wrote (a sha256 only with `--redact-claim`), the pinned scenario and support files' bytes, and passports "
        "(test ids and failure messages, secret-shaped values scrubbed). The claim text and the pinned bytes are "
        "kept as given, not scrubbed", "20 passports per claim; claims until unpinned; pinned bytes until uninstall")
    from .capabilities import _approvals_path, runs_dir
    add("capability approvals", "support", _approvals_path(root), "which capabilities you "
        "approved for this checkout, with binding hashes (journal: capabilities-journal.jsonl "
        "beside it)", "until revoked or uninstall")
    add("capability runs", "support", runs_dir(root), "capability run log and SARIF output "
        "(file paths, rule ids, finding locations)", "until uninstall")
    home = registry_home()
    add("pattern library", "patterns", home, "opt-in, per zone: sanitized stack recipes and "
        "aggregate outcomes; registered repo paths (local only)", "until removed")

    # Disclosure surfaces are reported even when the audit cannot enumerate a
    # provider's remote retention or user-chosen export paths.
    stores.extend([
        Store("provider transmission", "disclosure", "explicitly selected external provider", False, 0, None,
              "With explicit live execution/network authorization, task text, permitted source context, tool output "
              "and derived code may reach that provider. Repository zone policy and provider-specific approval "
              "must be checked. The current provider sandbox restricts writes, not all readable host files; "
              "it is not a complete read-isolation or exfiltration boundary. Temporary provider authentication "
              "and configuration copies are used; regex redaction cannot guarantee secrets are absent.",
              "remote retention follows provider policy; local uninstall cannot delete remote records", "n/a"),
        Store("user exports", "disclosure", "user-selected export and transcript paths", False, 0, None,
              "handoff receipts, evidence exports, shell redirects, copied diffs and logs can retain task text, "
              "paths, source-derived facts or code; exported skills also contain code-derived policy",
              "retained after uninstall; remove user exports explicitly", "n/a"),
    ])

    # Hard invariants: machine-local stores must not be committed.
    for store in stores:
        if store.kind in {"outcomes", "support"} and store.committed == "yes":
            store.problems.append("machine-local store is committed to git")
        if store.name == "episodes" and store.exists and \
                getattr(cfg, "learning_signals", "off") != "outcomes":
            store.problems.append("episodes exist but outcome recording is off "
                                  "(left over; `repo-ai learn forget --what episodes`)")
    return stores


def render(stores: list[Store]) -> str:
    lines = ["repo-ai privacy audit — every store, what it holds, and whether it is committed",
             "  (mission contracts keep redacted task text; verification evidence keeps "
             "the last lines of failing test output; the audit checks that. ProofLab keeps the claim text you "
             "pinned, unless --redact-claim, and the pinned scenario bytes as given: the audit does not scan them)"]
    for s in stores:
        size = f"{s.bytes / 1024:.1f} KB" if s.exists else "absent"
        entries = f", {s.entries} entries" if s.entries else ""
        lines.append(f"  [{s.kind}] {s.name}: {s.path} — {size}{entries}; committed: {s.committed}")
        lines.append(f"      holds: {s.contains}; retention: {s.retention}")
        for p in s.problems:
            lines.append(f"      PROBLEM: {p}")
    bad = sum(len(s.problems) for s in stores)
    lines.append("  result: " + ("PASS" if not bad else f"{bad} problem(s)"))
    lines.append("  PASS checks local store policy; this is not a complete secret or transmission audit.")
    lines.append("  delete outcome data: repo-ai learn forget   remove managed installation: repo-ai uninstall")
    lines.append("  User exports, provider records and user-owned settings/files can remain after uninstall.")
    return "\n".join(lines)
