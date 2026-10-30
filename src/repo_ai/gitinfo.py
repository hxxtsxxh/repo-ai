"""Git analysis.

Git history is used for exactly three things, all of them ranking signals:

  * **recency** — a file touched last week is more likely relevant to today's
    task than one untouched for three years
  * **hotspots** — high-churn files are where bugs and design pressure live
  * **change coupling** — files that keep changing together in the same commit
    are related in ways no import graph shows (a route and its migration; a
    schema and its client)

What we deliberately do *not* do: put commit messages or diffs into Bob's
standing context. That is noise with a token price. Bob can already read a
specific commit with `@<hash>` when it needs one.
"""

from __future__ import annotations

import re

import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .logging_setup import get_logger
from .models import GitFileStat

log = get_logger()

_TIMEOUT = 90


def _run(root: Path, args: list[str], timeout: int = _TIMEOUT) -> str:
    try:
        proc = subprocess.run(
            ["git", "--no-optional-locks", *args], cwd=root, capture_output=True, text=True,
            timeout=timeout, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("git %s failed: %s", " ".join(args[:2]), exc)
        return ""
    if proc.returncode != 0:
        log.debug("git %s exited %d: %s", " ".join(args[:2]), proc.returncode,
                  proc.stderr.strip()[:200])
        return ""
    return proc.stdout


@dataclass(slots=True)
class GitInfo:
    is_repo: bool = False
    head: str = ""
    branch: str = ""
    remote: str = ""
    root: str = ""
    commit_count: int = 0
    first_commit_iso: str = ""
    last_commit_iso: str = ""
    contributors: int = 0
    hotspots: list[GitFileStat] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)
    coupling: dict[str, list[str]] = field(default_factory=dict)
    dirty: bool = False

    def to_json(self) -> dict:
        data = asdict(self)
        data["hotspots"] = [asdict(h) for h in self.hotspots]
        return data

    @classmethod
    def from_json(cls, data: dict) -> "GitInfo":
        payload = dict(data)
        payload["hotspots"] = [GitFileStat(**h) for h in payload.get("hotspots", [])]
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


def current_head(root: Path) -> str:
    """Short HEAD sha, or empty string outside a git repository. Cheap."""
    return _run(root, ["rev-parse", "--short", "HEAD"], timeout=10).strip()


def is_git_repo(root: Path) -> bool:
    return (root / ".git").exists() or bool(
        _run(root, ["rev-parse", "--is-inside-work-tree"], timeout=10).strip() == "true"
    )


def find_repo_root(start: Path) -> Path:
    out = _run(start, ["rev-parse", "--show-toplevel"], timeout=10).strip()
    if out:
        return Path(out)
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start.resolve()


def collect(root: Path, days: int = 365, max_commits: int = 4000,
            tracked: set[str] | None = None) -> GitInfo:
    info = GitInfo()
    if not is_git_repo(root):
        return info
    info.is_repo = True
    info.root = str(root)
    info.head = _run(root, ["rev-parse", "--short", "HEAD"], timeout=10).strip()
    info.branch = _run(root, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=10).strip()
    info.remote = _run(root, ["config", "--get", "remote.origin.url"], timeout=10).strip()
    info.dirty = bool(_run(root, ["status", "--porcelain"], timeout=20).strip())

    count = _run(root, ["rev-list", "--count", "HEAD"], timeout=20).strip()
    info.commit_count = int(count) if count.isdigit() else 0
    info.first_commit_iso = _run(
        root, ["log", "--reverse", "--format=%cI", "--max-count=1"], timeout=30
    ).strip()[:19]
    info.last_commit_iso = _run(root, ["log", "-1", "--format=%cI"], timeout=10).strip()[:19]

    authors = _run(root, ["shortlog", "-sne", "--all", "--no-merges"], timeout=60)
    info.contributors = len([ln for ln in authors.splitlines() if ln.strip()])

    # --- numstat walk: churn, commit counts, authors, coupling ------------
    log_out = _run(root, [
        "log", f"--since={days}.days.ago", f"--max-count={max_commits}",
        "--no-merges", "--numstat", "--format=%x00%H%x00%an%x00%cI",
    ])
    if not log_out:
        log_out = _run(root, [
            "log", f"--max-count={min(max_commits, 800)}", "--no-merges",
            "--numstat", "--format=%x00%H%x00%an%x00%cI",
        ])

    commits_per_file: Counter[str] = Counter()
    churn_per_file: Counter[str] = Counter()
    authors_per_file: dict[str, set[str]] = defaultdict(set)
    last_touch: dict[str, str] = {}
    cochange: Counter[tuple[str, str]] = Counter()

    current_author = ""
    current_date = ""
    current_files: list[str] = []

    def flush() -> None:
        if len(current_files) > 1 and len(current_files) <= 25:
            unique = sorted(set(current_files))
            for i, a in enumerate(unique):
                for b in unique[i + 1:]:
                    cochange[(a, b)] += 1
        current_files.clear()

    for line in log_out.splitlines():
        if line.startswith("\x00"):
            flush()
            parts = line.split("\x00")
            if len(parts) >= 4:
                current_author, current_date = parts[2], parts[3][:19]
            continue
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) != 3:
            continue
        added, removed, path = cols
        if "=>" in path:  # rename: `old => new` or `dir/{a => b}/f`
            path = path.split("=>")[-1].strip().strip("}").replace("//", "/")
        if tracked is not None and path not in tracked:
            continue
        commits_per_file[path] += 1
        if added.isdigit():
            churn_per_file[path] += int(added)
        if removed.isdigit():
            churn_per_file[path] += int(removed)
        authors_per_file[path].add(current_author)
        last_touch.setdefault(path, current_date)
        current_files.append(path)
    flush()

    info.hotspots = [
        GitFileStat(
            path=path,
            commits=commits,
            last_commit_iso=last_touch.get(path, ""),
            authors=len(authors_per_file.get(path, ())),
            churn=churn_per_file.get(path, 0),
        )
        for path, commits in commits_per_file.most_common(120)
    ]

    recent = _run(root, [
        "log", "--max-count=120", "--no-merges", "--name-only", "--format=",
    ], timeout=60)
    seen: list[str] = []
    for path in recent.splitlines():
        path = path.strip()
        if path and path not in seen and (tracked is None or path in tracked):
            seen.append(path)
        if len(seen) >= 60:
            break
    info.recent_files = seen

    coupling: dict[str, list[str]] = defaultdict(list)
    for (a, b), together in cochange.most_common(600):
        if together < 3:
            break
        if len(coupling[a]) < 5:
            coupling[a].append(b)
        if len(coupling[b]) < 5:
            coupling[b].append(a)
    info.coupling = {k: v for k, v in coupling.items() if v}
    return info


def recency_scores(info: GitInfo, half_life_days: float = 60.0) -> dict[str, float]:
    """Map path -> 0..1 recency weight using exponential decay."""
    import datetime as _dt
    import math

    if not info.hotspots:
        return {}
    now = _dt.datetime.now(_dt.timezone.utc)
    scores: dict[str, float] = {}
    for stat in info.hotspots:
        if not stat.last_commit_iso:
            continue
        try:
            when = _dt.datetime.fromisoformat(stat.last_commit_iso)
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
        except ValueError:
            continue
        age_days = max((now - when).total_seconds() / 86400.0, 0.0)
        scores[stat.path] = math.exp(-age_days / half_life_days)
    for idx, path in enumerate(info.recent_files):
        scores[path] = max(scores.get(path, 0.0), 1.0 - idx / max(len(info.recent_files), 1) * 0.4)
    return scores


_SAFE_REF = re.compile(r"^(?!-)[A-Za-z0-9][A-Za-z0-9._/@{}~^-]{0,199}$")


def safe_ref(ref: str) -> bool:
    """A git revision that cannot be parsed as an option (`--output=...`).
    Refs can come from index metadata, which a repository could commit."""
    return bool(ref) and _SAFE_REF.match(ref) is not None and ".." not in ref


def changed_since(root: Path, ref: str) -> list[str]:
    """Files changed between `ref` and the working tree (staged + unstaged)."""
    if not safe_ref(ref):
        return []
    # -z: without it git C-quotes names with non-ASCII bytes, tabs, quotes or newlines
    # ("caf\303\251.py"), and such files silently dropped out of drift checks and diff scopes
    out = _run(root, ["diff", "--name-only", "-z", "--no-ext-diff", "--end-of-options", ref, "HEAD"], timeout=60)
    paths = {p for p in out.split("\0") if p}
    for args in (["diff", "--name-only", "-z", "--no-ext-diff"], ["diff", "--name-only", "-z", "--no-ext-diff",
                                                                  "--cached"],
                 ["ls-files", "-z", "--others", "--exclude-standard"]):
        extra = _run(root, args, timeout=60)
        paths.update(p for p in extra.split("\0") if p)
    return sorted(paths)
