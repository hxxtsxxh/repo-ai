"""Pre-PR Change Passport (`repo-ai review --changed`).

An evidence-based review packet for the working-tree (or branch) diff. It is
**not an approval**. It lists what the diff touches and what was or wasn't
checked:

- changed files by component, with additions and deletions;
- reverse dependencies (transitive importers);
- tests recommended for the change, and tests that recorded sessions show
  passing after the last edit (with outcome recording on);
- API, migration, dependency, config and CI risks, recognised from what
  changed;
- secret-scanner findings in *added* lines: rule name and `path:line`,
  never the value;
- explicit blind spots.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MIGRATION_RE = re.compile(r"(^|/)(migrations?|alembic|db/migrate|flyway|liquibase)(/|$)", re.I)
CI_RE = re.compile(r"(^|/)(\.github/workflows|\.gitlab-ci|Jenkinsfile|\.circleci|azure-pipelines)",
                   re.I)
MANIFESTS = {"package.json", "pyproject.toml", "requirements.txt", "go.mod", "pom.xml",
             "build.gradle", "Cargo.toml", "Gemfile", "composer.json"}
CONFIG_RE = re.compile(r"(^|/)(config|settings)[^/]*\.(py|ts|js|json|ya?ml|toml|ini)$|\.env\.example$",
                       re.I)


@dataclass(slots=True)
class Passport:
    base: str
    files: list[dict[str, Any]] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    importers: int = 0
    importers_sample: list[str] = field(default_factory=list)
    tests_recommended: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    tests_seen_passing: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    security: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _numstat(root: Path, base: str | None) -> list[tuple[str, int, int]]:
    """(path, added, removed) for every changed file. NUL-separated output, so names with spaces, tabs,
    quotes, non-ASCII, `{}` or ` => ` are read literally; a rename is reported under its new path."""
    proc = _git_plain(root, ["diff", "--numstat", "-z", "-M", "--no-ext-diff", "--no-textconv",
                             "--end-of-options", base or "HEAD"])
    out = []
    fields = proc.stdout.split("\0") if proc.returncode == 0 else []
    i = 0
    while i < len(fields):
        parts = fields[i].split("\t", 2)  # a tab may be part of the name
        if len(parts) != 3:
            i += 1
            continue
        add = int(parts[0]) if parts[0].isdigit() else 0
        rem = int(parts[1]) if parts[1].isdigit() else 0
        if parts[2]:
            path = parts[2]
            i += 1
        else:  # a rename: the old and new paths follow as their own fields
            path = fields[i + 2] if i + 2 < len(fields) else ""
            i += 3
        if path:
            out.append((path, add, rem))
    others = _git_plain(root, ["ls-files", "-z", "--others", "--exclude-standard"])
    for path in (others.stdout.split("\0") if others.returncode == 0 else []):
        if path and not path.startswith((".repo-ai/", ".claude/")):
            full = root / path
            n = 0
            try:
                if full.is_file() and not full.is_symlink() and full.stat().st_size < 5_000_000:
                    data = full.read_bytes()
                    n = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
            except OSError:
                n = 0
            out.append((path, n, 0))
    return out


def _rename_source(root: Path, rev: str, path: str) -> str:
    """The base-side path `path` was renamed from, or ""."""
    proc = _git_plain(root, ["diff", "--name-status", "-z", "-M", "--end-of-options", rev])
    fields = proc.stdout.split("\0") if proc.returncode == 0 else []
    i = 0
    while i < len(fields):
        status = fields[i]
        if status.startswith(("R", "C")) and i + 2 < len(fields):
            if fields[i + 2] == path and status.startswith("R"):
                return fields[i + 1]
            i += 3
        else:
            i += 2
    return ""


_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _git_plain(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """git that repository and user config cannot steer: no GIT_* variables, literal pathspecs, and diff
    options that override any colour, context, prefix, external diff or textconv setting."""
    # User and system config stay (core.autocrlf decides how a Windows working tree compares with the
    # blob); every setting that could hide or shift lines is overridden below, and no GIT_* variable
    # (GIT_EXTERNAL_DIFF, GIT_DIFF_OPTS, GIT_CONFIG_*) reaches git.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["LC_ALL"] = "C"
    argv = ["git", "-c", "core.quotepath=off", "-c", "color.ui=never", "-c", "diff.noprefix=false",
            "-c", "diff.mnemonicPrefix=false", "-c", "diff.relative=false", "-c", "diff.external=",
            "-c", "diff.interHunkContext=0", "--literal-pathspecs",
            "--no-optional-locks", *args]
    try:
        return subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(argv, 1, "", "")


def _added_lines(root: Path, base: str | None, path: str) -> list[tuple[int, str]]:
    """(line number, text) of every line the change adds to `path`. A file absent from the base, or a
    diff whose hunks cannot be read, counts as entirely new (the safe direction for review facts)."""
    def whole() -> list[tuple[int, str]]:
        full = root / path
        try:
            if not full.is_file() or full.is_symlink() or full.stat().st_size > 5_000_000:
                return []
            text = full.read_text("utf-8", errors="replace")
        except OSError:
            return []
        lines = text.split("\n")  # only \n ends a line: U+2028 or a form feed inside one does not
        if lines and lines[-1] == "":
            lines.pop()
        return list(enumerate(lines, 1))

    rev = base or "HEAD"
    paths = [path]
    if _git_plain(root, ["cat-file", "-e", f"{rev}:{path}"]).returncode != 0:
        source = _rename_source(root, rev, path)
        if not source:
            return whole()  # new or untracked
        paths = [source, path]  # a rename: only what changed inside it is new
    proc = _git_plain(root, ["diff", "--text", "--no-ext-diff", "--no-textconv", "--no-color",
                             *(["-M"] if len(paths) == 2 else ["--no-renames"]),
                             "-U0", "--inter-hunk-context=0", "--src-prefix=a/", "--dst-prefix=b/",
                             "--end-of-options", rev, "--", *paths])
    if proc.returncode != 0:
        return whole()
    out: list[tuple[int, str]] = []
    new_left = old_left = line_no = 0
    seen_hunk = False
    for line in proc.stdout.split("\n"):
        m = _HUNK.match(line)
        if m:  # count exactly the lines each hunk declares: a `+++` inside a hunk is content
            seen_hunk = True
            old_left = int(m.group(1)) if m.group(1) is not None else 1
            line_no = int(m.group(2))
            new_left = int(m.group(3)) if m.group(3) is not None else 1
            continue
        if new_left <= 0 and old_left <= 0:
            continue
        if line.startswith("+") and new_left > 0:
            out.append((line_no, line[1:]))
            line_no += 1
            new_left -= 1
        elif line.startswith("-") and old_left > 0:
            old_left -= 1
        elif line.startswith(" "):
            line_no += 1
            new_left -= 1
            old_left -= 1
    if proc.stdout.strip() and not seen_hunk and len(paths) == 1:
        return whole()  # the file differs but no hunk could be read (a pure rename has none)
    return out


def _only_managed_change(root: Path, base: str | None, path: str) -> bool:
    """An instruction file whose only change is repo-ai's managed block."""
    from .scanner import INSTRUCTION_FILES, analysis_text
    if PurePosixPath(path).name not in INSTRUCTION_FILES:
        return False
    try:
        now = (root / path).read_text("utf-8", errors="replace")
    except OSError:
        return False
    before = _git(root, "show", "--end-of-options", f"{base or 'HEAD'}:{path}")
    norm = lambda s: analysis_text(path, s).replace("\r\n", "\n").strip()  # noqa: E731
    return norm(now) == norm(before)


def build(root: Path, index, facts_obj, layout, base: str | None = None) -> Passport:
    from .episodes import load_all
    from .impact import analyze_impact
    from .security import scan_text

    passport = Passport(base=base or "HEAD (uncommitted changes)")
    changed = [(p, a, r) for p, a, r in _numstat(root, base)
               if not p.startswith((".repo-ai/", ".claude/", ".bob/context/"))
               and not _only_managed_change(root, base, p)]
    indexed = {row["path"]: row for row in index.all_files()}
    routes_by_file: dict[str, list[str]] = {}
    for route in index.routes(5000):
        routes_by_file.setdefault(route["file"], []).append(
            f"{route['method']} {route['path_pattern']}")
    for path, add, rem in changed:
        row = indexed.get(path)
        passport.files.append({"path": path, "added": add, "removed": rem,
                               "component": row["component"] if row else "",
                               "role": row["role"] if row else "unindexed"})
        name = PurePosixPath(path).name
        if path in routes_by_file:
            passport.risks.append(f"API: {path} serves {', '.join(routes_by_file[path][:4])}; "
                                  "check clients and API docs")
        if MIGRATION_RE.search(path):
            passport.risks.append(f"migration: {path}; check ordering, reversibility, and a "
                                  "backfill plan")
        if name in MANIFESTS or name.startswith("requirements"):
            passport.risks.append(f"dependencies: {path} changed; check lockfile and licences")
        if CI_RE.search(path):
            passport.risks.append(f"CI: {path} changed; it runs with repository secrets")
        if CONFIG_RE.search(path):
            passport.risks.append(f"config: {path} changed; check every environment")
        if row is None and not path.startswith(".repo-ai"):
            passport.blind_spots.append(f"{path} is not indexed (new, ignored, or binary)")
        for lineno, text in _added_lines(root, base, path)[:2000]:
            for finding in scan_text(path, text):
                passport.security.append(f"{finding.rule} at {path}:{lineno} "
                                         f"({finding.severity}; value not shown)")
    targets = [f["path"] for f in passport.files if f["path"] in indexed]
    passport.components = sorted({f["component"] for f in passport.files if f["component"]})
    if targets:
        impact = analyze_impact(index, facts_obj, targets, max_depth=3, root=root)
        passport.importers = len(impact.importers)
        passport.importers_sample = sorted(p for p, d in impact.importers.items() if d == 1)[:6]
        passport.tests_recommended = sorted(impact.tests)[:10]
        passport.commands = impact.commands[:4]
        passport.blind_spots += impact.uncertainty
    seen = set()
    for ep in load_all(layout)[-10:]:
        edits = ep.get("edits") or []
        if not edits or not set(targets) & {p for _, p in edits}:
            continue
        last = max(int(t) for t, _ in edits)
        for t, kind, cmd, ok in ep.get("commands") or []:
            if kind == "test" and ok and int(t) >= last and cmd not in seen:
                seen.add(cmd)
                passport.tests_seen_passing.append(cmd)
    if not passport.tests_seen_passing:
        passport.blind_spots.append("no recorded test run after the last edit to these files "
                                    "(run the recommended commands)")
    if not passport.tests_recommended and targets:
        passport.blind_spots.append("no linked tests for the changed files")
    passport.security = sorted(set(passport.security))
    passport.risks = sorted(set(passport.risks))
    return passport


def render(p: Passport) -> str:
    total_add = sum(f["added"] for f in p.files)
    total_rem = sum(f["removed"] for f in p.files)
    lines = [f"## Change passport (against {p.base})",
             "Evidence, not an approval: it shows what the diff touches and what was or wasn't "
             "checked.",
             f"\n**Changed**: {len(p.files)} file(s), +{total_add} / -{total_rem}; components: "
             f"{', '.join(p.components) or '-'}"]
    for f in p.files[:25]:
        lines.append(f"- `{f['path']}` +{f['added']}/-{f['removed']} ({f['role']})")
    lines.append(f"\n**Reverse dependencies**: {p.importers} transitive importer(s)"
                 + (f"; direct: {', '.join(p.importers_sample)}" if p.importers_sample else ""))
    lines.append("\n**Tests**")
    lines.append("- recommended: " + (", ".join(p.tests_recommended) or "none linked"))
    lines += [f"- run: `{c}`" for c in p.commands]
    lines.append("- seen passing after the last edit (recorded sessions): "
                 + (", ".join(f"`{c}`" for c in p.tests_seen_passing) or "none recorded"))
    lines.append("\n**Risks**")
    lines += [f"- {r}" for r in p.risks] or ["- none recognised from what changed"]
    lines.append("\n**Secret scanner (added lines)**")
    lines += [f"- {s}" for s in p.security] or ["- no findings"]
    lines.append("\n**Blind spots**")
    lines += [f"- {b}" for b in dict.fromkeys(p.blind_spots)] or ["- none listed"]
    return "\n".join(lines) + "\n"
