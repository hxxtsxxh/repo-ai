"""The verification workflow, end to end, behind one API that the CLI, JSON
consumers and agent hooks share:

    p = build_plan(root, layout)                 # read-only
    rec = run_plan(root, layout, p, executor)    # executes tests: needs authorization
    tm = record_evidence(root, layout, ...)      # executes tests: needs authorization

Tests never run in the repository. `run_plan` and `record_evidence` copy the
change into a disposable workspace (`isolate`), run there, delete it, and
check that the source tree is unchanged.
"""

from __future__ import annotations


import json
import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .. import sandbox
from . import cache, dynamic, evidence, isolate, results, strategy
from . import changes as ch
from .execute import Executor, release
from .runner import TestRunner
from .select import Graph, Plan, plan
from .testmap import TestMap, record, run_parallel

TESTMAP_NAME = "testmap.json"


class VerifyError(RuntimeError):
    pass


def establish_runner(root: Path, layout, override: str | None = None,
                     files: list[str] | None = None, override_source: str = "--test-command") -> TestRunner:
    """The trusted test runner: the user's `--test-command`, else the
    project's declared or inferred command (`commands.establish`), with its
    origin and every rule applied recorded on the runner."""
    from .commands import establish
    return establish(root, layout, files if files is not None else repo_files(root), override, override_source)


def repo_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=root, capture_output=True, timeout=60, check=False,
                         stdin=subprocess.DEVNULL).stdout.decode("utf-8", "replace").split("\0")
    return sorted(p for p in out if p and not p.startswith((".repo-ai/", ".bob/")) and (root / p).is_file())


def load_testmap(layout) -> TestMap | None:
    return TestMap.load(layout.state_dir / TESTMAP_NAME)


def build_plan(root: Path, layout, *, base: str = "HEAD", command: str | None = None,
               use_runtime: bool = True, index=None,
               command_source: str = "--test-command", paths: list[str] | None = None) -> tuple[Plan, ch.Change]:
    """The read-only plan for the working tree's change against `base`.
    `paths`: only the changed files among these repository-relative paths
    (a per-edit plan; its fingerprint covers only them, so it is never
    evidence for the whole change)."""
    files = repo_files(root)
    runner = establish_runner(root, layout, command, files, command_source)
    cmd = runner.command
    change = ch.detect(root, base, paths=paths)
    own_index = index is None
    if own_index:
        from ..index import open_index
        index = open_index(layout.state_dir) if layout.index_path.is_file() else None
    try:
        graph = Graph.from_index(index, files) if index is not None else Graph([], files)
        head = index.get_meta("git_head") if index is not None else ""
        names: dict[str, list[str]] = {}
        if index is not None:
            for row in index.conn.execute(
                    "SELECT src_path, test_path FROM test_links WHERE evidence != 'import'").fetchall():
                names.setdefault(row["src_path"], []).append(row["test_path"])
    finally:
        if own_index and index is not None:
            index.close()
    dyn = dynamic.analyze(root, files, cache_path=layout.state_dir / "verify-scan-cache.json")
    graph.add_inferred(dyn)
    tmap = load_testmap(layout) if use_runtime else None
    collection_note = _apply_collection(root, runner, files, tmap) if runner.kind == "pytest" else ""
    head = head if head and len(head) >= 7 and not _same_tree(
        root, head, change.base_commit, layout.state_dir / "verify-tree-pairs.json") else ""
    p = plan(change, runner, files, graph, dyn, tmap, index_head=head, name_links=names)
    if collection_note:
        p.uncertainty.append(collection_note)
    if change.withheld:
        p.uncertainty.append(f"{len(change.withheld)} untracked credential-like file(s) ({', '.join(change.withheld[:3])}) "
                             "are not part of the verified change: they are never copied where tests run")
    if not cmd:
        p.uncertainty.insert(0, "no test command could be established from the project's files; pass "
                                "`--test-command \"...\"` or set `verify_test_command` in .repo-ai/config.toml")
    return p, change


COLLECTION_CONFIG = {"pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "pyproject.toml", "tox.ini",
                     "setup.cfg", "conftest.py"}
_COLLECTION_KEYS = ("testpaths", "norecursedirs", "python_files", "collect_ignore", "--ignore", "--doctest",
                    "--deselect", "confcutdir", "rootdir")


def complete_collection(att: results.Attribution) -> bool:
    """pytest reported a module for every file whose tests it ran or listed."""
    ran = set(att.ended) | set(att.collected)
    return bool(ran) and ran <= att.modules


def collection_config(root: Path, files: list[str], runner: TestRunner) -> str:
    """What pytest's choice of test files depends on, besides the files
    themselves: every configuration file and conftest.py (any depth), the
    command and its environment. A recorded collection is used only while
    this is unchanged."""
    import hashlib
    h = hashlib.sha256(json.dumps([runner.command, runner.env, runner.cwd], sort_keys=True).encode())
    named = set()  # a configuration file the command names (`-c ci/pytest.ini`, `--config-file=...`)
    try:
        tokens = shlex.split(runner.command)
    except ValueError:
        tokens = []
    for i, tok in enumerate(tokens):
        value = tokens[i + 1] if tok in {"-c", "--config-file"} and i + 1 < len(tokens) else \
            tok.split("=", 1)[1] if tok.startswith("--config-file=") else ""
        if value:
            rel = str(PurePosixPath(runner.cwd or ".") / value) if not value.startswith("/") else value
            named.add(rel.removeprefix("./"))
    for f in sorted({f for f in files if PurePosixPath(f).name in COLLECTION_CONFIG} | named):
        h.update(f"\0{f}\0".encode())
        try:
            h.update((root / f).read_bytes())
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def _apply_collection(root: Path, runner: TestRunner, files: list[str], tmap) -> str:
    """Make the pytest universe the files pytest itself collected when the
    project's full suite last ran under `--record` (held-out-5 marshmallow:
    `norecursedirs` excluded `tests/mypy_test_cases`, which verify ran and
    reported as failing on every change). No static reading of pytest's
    configuration ever removes a file: only the recorded collection does, and
    only while every collection input is byte-identical. A test file added
    since the recording is never excluded. Returns an uncertainty note."""
    coll = (tmap.collected if tmap is not None else None) or {}
    if coll.get("files") and coll.get("command") == runner.command \
            and coll.get("config") == collection_config(root, files, runner):
        collected = set(coll["files"])
        static = set(runner.test_files(files))
        recorded = set(tmap.tests)
        leave_out = {f for f in static if f in recorded and f not in collected}
        if static and len(leave_out) * 2 > len(static):
            return (f"pytest's recorded collection would leave out {len(leave_out)} of {len(static)} test files; "
                    "that is not trusted (run `repo-ai verify --record` again)")
        runner.excluded = sorted({*runner.excluded, *leave_out})
        present = set(files)
        runner.included = sorted(f for f in collected if f in present and f not in static and f.endswith(".py"))
        if runner.excluded or runner.included:
            runner.notes.append(f"pytest's own recorded collection: {len(runner.excluded)} pattern-matched file(s) "
                                f"it does not collect are left out, {len(runner.included)} it collects are added")
        return ""
    if any(PurePosixPath(f).name in COLLECTION_CONFIG for f in files):
        for f in files:
            if PurePosixPath(f).name in COLLECTION_CONFIG:
                try:
                    text = (root / f).read_text("utf-8", errors="replace")
                except OSError:
                    continue
                if any(k in text for k in _COLLECTION_KEYS):
                    return (f"{f} configures which files pytest collects; the test files here are matched by name "
                            "(test_*.py, *_test.py) and may differ from what pytest runs. `repo-ai verify --record` "
                            "learns pytest's own collection")
    return ""


OWN_PATHS = (".repo-ai/", ".claude/", ".bob/", ".gitignore", "CLAUDE.md", "AGENTS.md")


def _same_tree(root: Path, indexed: str, base: str, cache_path: Path | None = None) -> bool:
    """True when the commit the index was built at and the base differ only in
    files repo-ai itself writes (committing `repo-ai init` output is common).
    Two commit ids always give the same answer, so it is remembered in
    `cache_path` (bounded)."""
    from ..gitinfo import safe_ref
    if not base or not safe_ref(indexed) or base.startswith(indexed):
        return True
    import hashlib
    import json
    # the answer depends on the commits and on what counts as repo-ai's own files
    key = f"{indexed}..{base}:" + hashlib.sha256(repr(OWN_PATHS).encode()).hexdigest()[:12]
    cache: dict = {}
    if cache_path is not None:
        try:
            cache = json.loads(cache_path.read_text("utf-8"))
        except (OSError, ValueError):
            cache = {}
        if not isinstance(cache, dict):
            cache = {}
        if isinstance(cache.get(key), bool):
            return cache[key]
    # --no-renames: a source file moved into repo-ai's own directory is a deleted source file,
    # not "only repo-ai's files changed"; the answer must not depend on diff configuration
    out = subprocess.run(["git", "diff", "--no-renames", "--no-ext-diff", "--name-only", "-z", "--end-of-options",
                          indexed, base], cwd=root, capture_output=True, text=True, timeout=60, check=False,
                         stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        return False  # not remembered: the commit may become available
    same = all(p.startswith(OWN_PATHS) for p in out.stdout.split("\0") if p)
    if cache_path is not None:
        cache[key] = same
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(dict(list(cache.items())[-200:])), "utf-8")
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return same


class SourceTreeChanged(VerifyError):
    pass


# Git's own bookkeeping that ordinary work outside the run changes (another session's commit in
# a linked worktree writes objects, logs and refs; `git status` refreshes the index). Everything
# else stays checked: `.git/HEAD`, `.git/config`, `.git/hooks/`, info/, and each linked worktree's
# and submodule's own config and hooks. Refs are left out, so the commit HEAD resolves to is
# compared separately (`_head`): moving the checked-out branch is never bookkeeping.
GIT_BOOKKEEPING = (".git/objects/", ".git/logs/", ".git/refs/", ".git/index", ".git/packed-refs",
                   ".git/FETCH_HEAD", ".git/ORIG_HEAD", ".git/COMMIT_EDITMSG", ".git/gc.", ".git/lfs/",
                   ".git/rr-cache/")
# inside .git/worktrees/<name>/ (another worktree's checkout state) and .git/modules/<path>/
WORKTREE_BOOKKEEPING = ("logs/", "index", "HEAD", "ORIG_HEAD", "COMMIT_EDITMSG", "AUTO_MERGE")
MODULE_BOOKKEEPING = ("objects/", "logs/", "refs/", "index", "packed-refs", "FETCH_HEAD", "ORIG_HEAD",
                      "COMMIT_EDITMSG")


def _git_bookkeeping(root: Path) -> list[str]:
    out = list(GIT_BOOKKEEPING)
    git = root / ".git"
    if not git.is_dir() or git.is_symlink():
        return out
    try:
        for wt in os.scandir(git / "worktrees"):
            if wt.is_dir(follow_symlinks=False):
                out += [f".git/worktrees/{wt.name}/{x}" for x in WORKTREE_BOOKKEEPING]
    except OSError:
        pass
    stack = [git / "modules"]  # nested submodules keep theirs in modules/<a>/modules/<b>
    while stack:
        cur = stack.pop()
        try:
            entries = [e for e in os.scandir(cur) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in entries:
            rel = Path(e.path).relative_to(root).as_posix()
            if (Path(e.path) / "HEAD").is_file():
                out += [f"{rel}/{x}" for x in MODULE_BOOKKEEPING]
                stack.append(Path(e.path) / "modules")
            else:
                stack.append(Path(e.path))  # a submodule path with slashes
    return out


def _head(root: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, capture_output=True,
                         text=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    return out.stdout.strip() if out.returncode == 0 else ""


def _other_worktrees_added_or_removed(before: isolate.Snapshot, after: isolate.Snapshot,
                                      diff: list[str]) -> list[str]:
    """Another session adding or removing a linked worktree creates or deletes
    its whole `.git/worktrees/<name>/`: that is not a change to this tree."""
    def names(s: isolate.Snapshot) -> set[str]:
        return {k.split("/")[2] for k in s.stat if k.startswith(".git/worktrees/") and k.count("/") == 2}
    moved = names(before) ^ names(after)
    return [d for d in diff if not (d.startswith(".git/worktrees/") and d.split("/")[2].split(":")[0] in moved)]


def _own_state(root: Path, layout) -> tuple[str, ...]:
    """What the integrity check leaves out: repo-ai's own directories, which a
    run writes by design (timings, base outcomes, evidence) and which other
    sessions' hooks and refreshes write while it runs (generated context, the
    learning ledger), and git's bookkeeping (above). Every other working-tree
    file is hashed before and after the run.

    A directory named by configuration, which a repository can commit, is
    never left out whole unless it is one of repo-ai's default directories
    (`DEFAULT_DIRS`). For any other state directory, only the files repo-ai
    itself writes there (`STATE_FILES`: data names, never code) are left
    out, and never one that git tracked or showed when the run began; and
    only when the directory is repo-ai's own output directory too (`out_dir`)
    or git ignores it. Nothing
    inside `.git` is ever left out by configuration (its config and hooks stay
    checked). So `state_dir = "src"`, `".git/hooks"`, `".bob/hooks"` or
    `".venv"` hides nothing a run could plant, and in a state directory only
    data files of repo-ai's own names are left out (`STATE_FILES`). A configured context or
    learning directory elsewhere is checked like the rest of the tree: a
    concurrent refresh there makes the run fail closed."""
    skip = [".repo-ai/state/", *_git_bookkeeping(root)]
    for attr in ("state_rel", "context_rel", "learning_rel"):
        try:
            rel = getattr(layout, attr) if layout is not None else ""
        except ValueError:  # outside the repository: nothing under the root to skip
            rel = ""
        rel = rel.rstrip("/")
        if not rel or rel == "." or rel.startswith("../"):
            continue
        if rel in DEFAULT_DIRS or (rel.startswith(".repo-ai/") and rel != ".repo-ai"):
            skip.append(rel + "/")  # repo-ai's own directories (Session A's rework of #53); `.repo-ai` itself is not
        elif attr == "state_rel" and not _inside_git(rel) and (_shared(layout) or _ignored(root, rel)):
            # repo-ai's own runtime files only (data names, never code), and never a file git tracked or showed when
            # the run began (`isolate._skipped`): a state directory shared with committed docs keeps them checked;
            # elsewhere (a state_dir that points into source) only when git ignores the directory
            skip += ["re:" + re.escape(rel) + "/" + STATE_FILES, "redir:" + re.escape(rel) + STATE_DIRS]
    return tuple(dict.fromkeys(skip))


# repo-ai's own directories in its default and legacy layouts (`paths.py`)
DEFAULT_DIRS = frozenset({".repo-ai/state", ".repo-ai/context", ".repo-ai/learning", ".bob/context",
                          ".bob/context/learning"})
# what repo-ai writes in a state directory, as a pattern for one file: the index, caches, locks and markers,
# verify's and ProofLab's records (data files only: a `.pth` file or a module there is always checked, since
# a state directory inside an import path would load it)
STATE_FILES = (r"(?:index\.db(?:-wal|-shm)?|\.dirty(?:\.processing)?|update\.lock|last-refresh|signals\.jsonl|"
               r"originals\.json|flight\.jsonl|ranking\.json|runs\.jsonl|testmap\.json|gate\.json|verify-[\w.-]*\.json|"
               r"(?:evidence|prove|episodes|backups|sarif)/(?:[^/]+/)*(?:[0-9a-f]{64}|(?!package\.json$)[^/]+\.(?:json|jsonl|sarif|lock)))")
STATE_DIRS = r"(?:/(?:evidence|prove|episodes|backups|sarif)(?:/[^/]+)*)?"  # the directory itself, and those




def _shared(layout) -> bool:
    """The state directory is also where repo-ai writes its generated
    context (`out_dir`, the legacy layout): repo-ai's own output directory."""
    try:
        return bool(layout is not None and layout.state_rel and layout.state_rel == layout.context_rel)
    except ValueError:
        return False


def _ignored(root: Path, rel: str) -> bool:
    """git ignores the directory `rel` (False when git cannot say)."""
    try:
        out = subprocess.run(["git", "check-ignore", "-q", "--no-index", "--", rel.rstrip("/") + "/"], cwd=root,
                             capture_output=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _inside_git(rel: str) -> bool:
    """`rel` is `.git` or below it, in any letter case (macOS: `.GIT` is `.git`)."""
    return any(part.casefold() == ".git" for part in rel.replace("\\", "/").split("/"))




def _prepare(root: Path, change: ch.Change, label: str, log: Callable[[str], None],
             listing: tuple[list[str], list[str]] | None = None,
             layout=None) -> tuple[isolate.Snapshot, isolate.Workspace, str]:
    """Snapshot the source tree, copy the change into a disposable workspace,
    and confirm the copy is the change the plan describes. Also returns the
    change's semantic fingerprint from that same fresh reading (valid for the
    run when the integrity check finds the tree unchanged afterwards)."""
    listing = listing or isolate.worktree_files(root)
    before = isolate.snapshot(root, listing[0], skip=_own_state(root, layout))
    before.head = _head(root)
    ws = isolate.materialize(root, label=label, listing=listing)
    try:  # read again now, after the copy: never from the plan's listing
        now, semantic = ch.fingerprints(root, change.base)
    except ch.ChangeError:
        now = semantic = ""
    if now != change.fingerprint:
        ws.cleanup()
        raise VerifyError("the working tree changed while the run was being prepared; run it again")
    log(f"  isolated copy: {len(ws.files)} files ({ws.method}, {ws.seconds:.1f}s)"
        + (f"; withheld {len(ws.withheld)} credential-like untracked file(s)" if ws.withheld else "")
        + (f"; read-only: {', '.join(sorted(ws.readonly))}" if ws.readonly else ""))
    return before, ws, semantic


def _integrity(root: Path, before: isolate.Snapshot) -> dict[str, Any]:
    after = isolate.snapshot(root, list(before.content), skip=before.skip)
    diff = _other_worktrees_added_or_removed(before, after, before.changes(after))
    head = _head(root)
    if head != before.head:
        diff.insert(0, f"HEAD: moved from {before.head[:12] or '(none)'} to {head[:12] or '(none)'}")
    return {"unchanged": not diff, "changes": diff[:50], "entries_checked": len(before.stat),
            "files_hashed": len(before.content), "check_seconds": round(before.seconds + after.seconds, 3)}


def run_plan(root: Path, layout, p: Plan, change: ch.Change, executor: Executor, *, full: bool = False,
             workers: int = 4, timeout_s: float = 600.0, timeout_explicit: bool = False, reuse: bool = True,
             deadline_s: float | None = None, log: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    """Execute the plan in the sandbox. Runs repository code: the caller must
    hold the user's explicit authorization (`verify --run`).

    `reuse`: when evidence exists for this exact change, environment, test
    command and selection (younger than a day), report it instead of running
    the same tests again.

    `deadline_s`: a total wall-clock budget for every sandboxed process of the
    run. No process limit is ever extended past it; a process it cuts, or one
    it leaves no time to start, makes the run "not verified" (never a pass,
    and never a new failure by itself)."""
    listing = isolate.worktree_files(root)
    links = {rel: str((root / rel).resolve()) for rel in isolate.dependency_dirs(root, listing[0])}
    env_key = cache.environment_key(executor, p.runner, links=links)
    key = _reuse_key(p, change, env_key, full, timeout_s if timeout_explicit else None, deadline_s)
    if reuse:
        old = evidence.find_reusable(layout.state_dir, key)
        if old is not None:
            evidence.set_latest(layout.state_dir, old)
            log(f"  reusing the evidence from {old.get('created')}: same change, environment, test command and "
                "selection (`--rerun` runs it again)")
            return old
    static = cache.static_environment(executor, p.runner, links=links)  # before the run: a change during it is stale
    before, ws, semantic = _prepare(root, change, "run", log, listing, layout=layout)
    try:
        rec = _run_isolated(root, layout, p, change, executor.in_workspace(ws), full=full, workers=workers,
                            timeout_s=timeout_s, timeout_explicit=timeout_explicit, env_key=env_key, log=log,
                            deadline_s=deadline_s)
    finally:
        ws.cleanup()
    rec["environment_static"] = static
    rec["source_tree"] = _integrity(root, before)
    if not rec["source_tree"]["unchanged"]:
        rec["verdict"] = "invalid: the source tree changed during the run"
    else:
        rec["reuse_key"] = key
        if semantic:  # the completion gate accepts a later rewrite that cannot change behaviour
            rec["semantic_fingerprint"] = semantic
    rec["path"] = str(evidence.save(layout.state_dir, rec, latest=bool(rec["source_tree"]["unchanged"]))
                      .relative_to(root))
    if not rec["source_tree"]["unchanged"]:
        raise SourceTreeChanged("the source tree changed while tests ran (" + "; ".join(
            rec["source_tree"]["changes"][:3]) + "). The evidence is marked invalid; if you were not "
            "editing, report this: tests must never be able to write to it")
    return rec


def _reuse_key(p: Plan, change: ch.Change, env_key: str, full: bool, timeout_s: float | None = None,
               deadline_s: float | None = None) -> str:
    import hashlib
    import json
    data = {"fingerprint": change.fingerprint, "base": change.base_commit, "env": env_key,
            **({"timeout": timeout_s} if timeout_s is not None else {}),  # an explicit limit is part of the question
            **({"deadline": deadline_s} if deadline_s is not None else {}),
            "selected": sorted(s.test for s in p.selected), "full": bool(full or p.full_suite_required),
            "universe": p.universe, "excluded": sorted(p.runner.excluded)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:32]


@dataclass(slots=True)
class _Ctx:
    root: Path
    layout: Any
    p: Plan
    change: ch.Change
    runner: TestRunner
    toolchain: str
    executor: Executor            # template of the change: nothing runs in it, every process clones it
    workers: int
    timeout_s: float
    timeout_explicit: bool
    durations: dict[str, float | None]
    timings: cache.Timings
    env_key: str
    log: Callable[[str], None]
    processes: dict[str, int] = field(default_factory=dict)
    file_runs: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    skips: dict[str, tuple[int, int]] = field(default_factory=dict)  # file -> (tests, skipped) at the change
    watch_s: dict[str, float | None] = field(default_factory=dict)  # what watchdog budgets are based on
    deadline: float | None = None  # monotonic time by which every process of the run must have ended
    deadline_hit: bool = False     # a process was cut by it, or not started for lack of time

    def count(self, phase: str, files: list[str] | None = None) -> None:
        with self.lock:
            self.processes[phase] = self.processes.get(phase, 0) + 1
            if files is not None:
                for f in files:
                    self.file_runs[f] = self.file_runs.get(f, 0) + 1


def _process(ctx: _Ctx, template: Executor, argv: list[str], files: list[str], limit: float, phase: str,
             count_files: bool = True, owners: dict[str, list[str]] | None = None, native: bool = False
             ) -> tuple[Any, results.Attribution | None]:
    """One sandboxed test process in a fresh clone of `template`, reporting
    per-test outcomes when the runner allows it. Under a deadline its limit
    is cut to the time left, and a process with no time left does not run."""
    capped = False
    if ctx.deadline is not None:
        left = ctx.deadline - time.monotonic()
        if left < 1.0:
            ctx.deadline_hit = True
            ctx.log(f"  not run ({phase}): the time budget ran out")
            return sandbox.Result(exit_code=-1, stdout="", stderr="", duration_s=0.0, timed_out=True,
                                  backend=template.backend.name, notes=[DEADLINE_NOTE]), None
        if left < limit:
            limit, capped = left, True
    ex = template.fresh()
    try:
        assert ex.workspace is not None
        report = None
        run_argv = argv
        if results.can_instrument(ctx.runner, argv):
            run_argv, report = results.instrument(ctx.runner, argv, ex.workspace.path, ex.inside_root, "outcomes",
                                                  native=native)
        ctx.count(phase, files if count_files else None)
        watch = _watch(ctx, report, ex.inside_root, files, limit, phase)
        try:
            res = ex.run(run_argv, cwd=ctx.runner.cwd, env=ctx.runner.env, timeout_s=limit,
                         toolchain=ctx.toolchain, watch=watch)
        finally:
            if watch is not None:
                watch.close()
        att = (results.parse(report, ctx.runner, files, ex.inside_root, exit_code=res.exit_code,
                             timed_out=res.timed_out, owners=owners) if report is not None else None)
        if capped and res.timed_out and res.duration_s >= limit - 1.0 \
                and not any(n.startswith("watchdog") for n in res.notes):  # a stall is the watchdog's, not ours
            ctx.deadline_hit = True
            res = replace(res, notes=[*res.notes, DEADLINE_NOTE])
        why = results.hides_failure(att) if res.exit_code == 0 and not res.timed_out else ""
        if why and report is not None:  # the report outranks the exit status: the run failed, attributed as one
            res = replace(res, exit_code=1, notes=[*res.notes, f"exit status 0 not accepted: {why}"])
            att = results.parse(report, ctx.runner, files, ex.inside_root, exit_code=1, timed_out=False,
                                owners=owners)
    finally:
        release([ex])
    if att is not None and phase not in {"base", "confirm"}:
        with ctx.lock:
            for f in files:
                fo = att.files.get(f)
                if fo is not None and fo.tests:
                    ctx.skips[f] = (fo.tests, fo.skipped)
    return res, att


WATCHED_PHASES = {"file", "batch", "full", "rerun"}
DEADLINE_NOTE = "cut by the run's time budget (--deadline)"


def _watch(ctx: _Ctx, report, inside_root: str, files: list[str], limit: float, phase: str = "file"):
    """The per-test progress watchdog for this process (`watchdog.Watch`), or
    None: only for runners whose report streams a line per test start and end
    (unittest, pytest), never with an explicit `--timeout` (the limit is then
    the user's), only with measured times (budgets come from them), and only
    for runs of the change. Base and confirmation runs keep the hard limit:
    budgets are learned from the change's code, and a base run cut by one
    would read as failing at the base and could make a new failure look
    pre-existing."""
    if report is None or ctx.runner.kind not in {"unittest", "pytest"} or ctx.timeout_explicit \
            or phase not in WATCHED_PHASES:
        return None
    from . import watchdog
    measured = {f: ctx.watch_s.get(f) for f in files}
    budgets = {f: watchdog.budget(s, limit) for f, s in measured.items()}
    if not any(b is not None for b in budgets.values()):
        return None
    # before its first event the process imports and collects every file it was given, so that
    # wait is bounded by their measured times together, not by the start-up of a small batch
    known = list(measured.values())
    start = watchdog.budget(sum(known), limit) if known and all(known) else None  # type: ignore[arg-type]
    return watchdog.Watch(report, inside_root, budgets, start, limit)


def _unfinished(res, limit: float) -> str:
    """Why a test that started never finished: the watchdog's reason, or the limit."""
    for note in getattr(res, "notes", None) or []:
        if note.startswith("watchdog: "):
            return note[len("watchdog: "):]
    return f"did not finish within {limit:.0f}s"


def _status(res) -> str:
    return "timeout" if res.timed_out else ("pass" if res.exit_code == 0 else "fail")


NO_TESTS = "no-tests"
_NO_TESTS_EXIT = 5  # unittest (3.12+) and pytest: the run found no test to run


def _empty(ctx: _Ctx, res, att: results.Attribution | None, f: str, failures: dict[str, str]) -> bool:
    """The file defines no test (a helper module matched by the runner's
    pattern): neither a pass nor a failure, and never counted as verified."""
    if failures:
        return False
    if res.exit_code == _NO_TESTS_EXIT and not res.timed_out and ctx.runner.kind in {"unittest", "pytest"}:
        return True
    fo = att.files.get(f) if att is not None and att.trusted else None
    return fo is not None and fo.status == "pass" and fo.ran == 0 and not fo.failing


def _row(ctx: _Ctx, test: str, status: str, res, argv: list[str], failures: dict[str, str], text: str, *,
         duration: float, shape: str, attributed: bool, seconds: dict[str, float] | None = None) -> dict[str, Any]:
    """One test file's result. `shape`: how it ran (`file` alone, in a
    `batch` of files, or in the `full` suite)."""
    bad = status not in {"pass", NO_TESTS}
    if bad and shape != "file" and attributed and failures:
        # several files shared the process: show this file's failures, not the process's output
        tail = evidence.scrub("\n".join(f"{tid}: {msg}" if msg else tid for tid, msg in sorted(failures.items())[:12]))
    else:
        tail = evidence.failure_excerpt(text) if bad else ""
    return {"test": test, "status": status, "exit_code": res.exit_code, "duration_s": round(duration, 2),
            # only a file the budget actually cut: one that finished before it keeps its own result
            **({"deadline": True} if DEADLINE_NOTE in res.notes and status == "timeout" else {}),
            "command": ctx.runner.display(argv), "batched": shape != "file", "shape": shape,
            "attributed": attributed, "failing_tests": sorted(failures)[:200] if bad else [],
            "failures": {k: evidence.scrub(v, 300) for k, v in sorted(failures.items())[:50]} if bad else {},
            "failing_test_seconds": {k: round(v, 3) for k, v in sorted((seconds or {}).items())[:50]} if bad else {},
            "output_tail": tail}


def _limit(ctx: _Ctx, files: list[str]) -> float:
    known = [ctx.durations.get(f) for f in files]
    if None in known:
        return ctx.timeout_s
    est = strategy.batch_cost(files, ctx.durations, strategy.startup_estimate(ctx.durations, ctx.timings.startup_s),
                              1.0)
    cap = ctx.timeout_s if len(files) == 1 else min(ctx.timeout_s * len(files),
                                                   max(60.0, 3 * sum(k or 0 for k in known)))
    return strategy.process_limit(est, cap, ctx.timeout_explicit)


def _run_file(ctx: _Ctx, test: str, phase: str = "file") -> dict[str, Any]:
    """One test file alone, at the change. `phase`: "file" when it is the
    planned shape, "rerun" when a batch could not be attributed."""
    argv = ctx.runner.file_argv(test)
    limit = _limit(ctx, [test])
    res, att = _process(ctx, ctx.executor, argv, [test], limit, phase)
    status = _status(res)
    text = res.stderr + "\n" + res.stdout
    failures: dict[str, str] = {}
    if status != "pass":
        fo = att.files.get(test) if att is not None else None
        if fo is not None and (fo.failing or fo.hung):
            failures = dict(fo.failing)
            for tid in fo.hung:
                failures.setdefault(tid, _unfinished(res, limit))
        else:
            failures = {tid: "" for tid in evidence.failing_tests(text)}
    if status != "timeout" and _empty(ctx, res, att, test, failures):
        status, failures = NO_TESTS, {}
    if status == "pass":  # a failing run (an import error) says nothing about how long the file takes
        # a run that skipped most of the file's tests is no measure of its worst case: it updates the
        # blend, never the peak a watchdog budget comes from (the peak would decay toward it)
        tests, skipped = ctx.skips.get(test, (0, 0))
        ctx.timings.note_file(test, res.duration_s, own_process=not (tests and 2 * skipped > tests))
    ctx.log(f"  {status:7s} {test} ({res.duration_s:.1f}s)")
    return _row(ctx, test, status, res, argv, failures, text, duration=res.duration_s, shape="file",
                attributed=att is not None and att.trusted)


def _run_batch(ctx: _Ctx, files: list[str], retry: bool = True) -> list[dict[str, Any]]:
    """Several test files as one process. A passing batch vouches for every
    file in it. A failing batch is attributed per file from its per-test
    report when that report is trustworthy (`results.parse`); otherwise its
    files are re-run one by one, exactly as in per-file mode."""
    if len(files) == 1:
        return [_run_file(ctx, files[0])]
    argvs = ctx.runner.group_argvs(files)
    if len(argvs) != 1:
        return [_run_file(ctx, f) for f in files]
    argv = argvs[0]
    limit = _limit(ctx, files)
    res, att = _process(ctx, ctx.executor, argv, files, limit, "batch")
    text = res.stderr + "\n" + res.stdout
    if res.exit_code == 0 and not res.timed_out:
        ctx.log(f"  pass    batch of {len(files)} file(s) ({res.duration_s:.1f}s)")
        _learn_from_batch(ctx, files, res, att)
        share = res.duration_s / len(files)
        return [_row(ctx, f, _batch_status(att, f, "pass"), res, argv, {}, "", shape="batch",
                     attributed=att is not None and att.trusted,
                     duration=(att.files[f].seconds if att is not None and att.trusted else share)) for f in files]
    if (res.exit_code == _NO_TESTS_EXIT and not res.timed_out and att is not None and att.done
            and not att.unmapped and not att.failing_files()):
        return [_row(ctx, f, _batch_status(att, f, "pass"), res, argv, {}, "", shape="batch", attributed=True,
                     duration=att.files[f].seconds) for f in files]  # nothing failed; some files had no tests
    if att is not None and att.trusted:
        bad = att.failing_files()
        ctx.log(f"  fail    batch of {len(files)} file(s) ({res.duration_s:.1f}s): {len(bad)} failing file(s), "
                "attributed from the per-test report")
        _learn_from_batch(ctx, files, res, att)
        return [_row(ctx, f, _batch_status(att, f, att.files[f].status), res, argv, att.files[f].failing, text,
                     shape="batch", attributed=True, duration=att.files[f].seconds,
                     seconds=att.files[f].test_seconds) for f in files]
    hung = [f for f in files if att is not None and att.files[f].hung]
    if res.timed_out and len(hung) == 1 and att is not None and not att.unmapped \
            and ctx.runner.kind in {"unittest", "pytest"}:
        # these runners take the files one after another: the files whose tests started before the
        # one still running had finished, the hung file is known, and the rest never started
        f = hung[0]
        # ... unless their tests interleave (a plugin reorders them): a file before the hung one counts
        # as finished only when every test it was about to run ended; any other file runs again
        finished = [x for x in att.order[:att.order.index(f)] if att.complete(x)] if f in att.order else []
        pending = [x for x in files if x != f and x not in att.order]
        ctx.log(f"  timeout batch of {len(files)} file(s) after {limit:.0f}s: {f} did not finish; "
                f"{len(finished)} finished before it" + (f"; running the {len(pending)} not yet started"
                                                          if pending else ""))
        failures = {tid: _unfinished(res, limit) for tid in att.files[f].hung}
        failures.update(att.files[f].failing)
        out = [_row(ctx, f, "timeout", res, argv, failures, text, shape="batch", attributed=True,
                    duration=res.duration_s)]
        out += [_row(ctx, x, _batch_status(att, x, att.files[x].status), res, argv, att.files[x].failing, text,
                     shape="batch", attributed=True, duration=att.files[x].seconds,
                     seconds=att.files[x].test_seconds) for x in finished]
        rest = [x for x in files if x != f and x not in finished]
        if set(rest) - set(pending):  # a file that started out of order: nothing about it can be trusted
            pending = rest
        return out + (_run_batch(ctx, pending) if pending else [])
    if res.timed_out and att is not None and not att.unmapped and ctx.runner.kind == "node":
        # node runs each file in its own child process: a file that completed has its results, a
        # file that started and never completed hung, and a file that never started runs again
        started = set(att.order)
        reported = _node_reported(att)
        hung_files = [x for x in files if x in started and x not in att.finished]
        done = [x for x in files if x in reported]
        # never started, or completed but its results not (all) in the report yet: runs again
        pending = [x for x in files if x not in done and x not in hung_files]
        ctx.log(f"  timeout batch of {len(files)} file(s) after {limit:.0f}s: {len(done)} finished, "
                f"{len(hung_files)} did not finish" + (f"; running the {len(pending)} not yet started"
                                                       if pending else ""))
        out = [_row(ctx, x, "timeout", res, argv, {**{tid: _unfinished(res, limit)
                                                        for tid in att.files[x].hung}, **att.files[x].failing},
                    text, shape="batch", attributed=True, duration=res.duration_s) for x in hung_files]
        out += [_row(ctx, x, _batch_status(att, x, att.files[x].status), res, argv, att.files[x].failing, text,
                     shape="batch", attributed=True, duration=att.files[x].seconds,
                     seconds=att.files[x].test_seconds) for x in done]
        # a completed file whose results were not in the report did not hang: those run again together;
        # a file that never completed may be the hung one, so it runs alone unless this was the first
        # attempt and something was learned (re-running the identical batch would hang the same way)
        completed = [x for x in pending if x in att.finished]
        unknown = [x for x in pending if x not in att.finished]
        if completed:
            out += _run_batch(ctx, completed, retry=False) if len(completed) > 1 else [_run_file(ctx, completed[0],
                                                                                                 "rerun")]
        if unknown and retry and len(unknown) < len(files):
            out += _run_batch(ctx, unknown, retry=False)
        elif unknown:
            out += [_run_file(ctx, x, "rerun") for x in unknown]
        return out
    if res.timed_out and len(hung) == 1 and retry:
        # the test that was running when the limit hit is known: report it, re-run the rest together
        f = hung[0]
        ctx.log(f"  timeout batch of {len(files)} file(s) after {limit:.0f}s: {f} did not finish; "
                "re-running the others together")
        assert att is not None
        failures = {tid: _unfinished(res, limit) for tid in att.files[f].hung}
        row = _row(ctx, f, "timeout", res, argv, failures, text, shape="batch", attributed=True,
                   duration=res.duration_s)
        return [row] + _run_batch(ctx, [x for x in files if x != f], retry=False)
    why = att.reason if att is not None else "this runner gives no per-test report"
    ctx.log(f"  {_status(res):7s} batch of {len(files)} file(s) ({why}): re-running them one by one, each in a "
            "fresh copy")
    return [_run_file(ctx, f, "rerun") for f in files]


def _node_reported(att: results.Attribution) -> set[str]:
    """The node files whose results the report holds in full. node writes a
    file's test events only when its turn comes, after every earlier file's,
    while the file's own completion (`file_done`) arrives at once: a file that
    completed while an earlier one was still running has no results in the
    report yet, and counting it as finished would report a failing file as
    passing. A completed file counts once a later file's events follow its own
    (the last file reported may have been cut while its events were written),
    or when the whole run reported its end."""
    order = att.order
    reported = {f for f in order[:-1] if f in att.finished}
    if order and att.done and order[-1] in att.finished:
        reported.add(order[-1])
    return reported


def _batch_status(att: results.Attribution | None, f: str, status: str) -> str:
    """A file in a multi-file process in which no test ran has no tests."""
    if status == "pass" and att is not None and (att.trusted or att.done) and f in att.files \
            and att.files[f].ran == 0 and not att.files[f].failing:
        return NO_TESTS
    return status


def _learn_from_batch(ctx: _Ctx, files: list[str], res, att: results.Attribution | None) -> None:
    """A trusted report of a passing multi-file process measures the fixed
    cost of a process (its wall time minus the time inside tests) and each
    file's own share. Failing processes are not representative (an import
    error ends a file at once) and teach nothing."""
    if att is None or not att.trusted or res.timed_out or res.exit_code != 0:
        return
    inside = sum(att.files[f].seconds for f in files)
    startup = max(0.02, res.duration_s - inside)
    ctx.timings.note_startup(startup)
    for f in files:
        ctx.timings.note_file(f, startup + att.files[f].seconds, own_process=False)


def _run_isolated(root: Path, layout, p: Plan, change: ch.Change, executor: Executor, *, full: bool,
                  workers: int, timeout_s: float, timeout_explicit: bool, env_key: str,
                  log: Callable[[str], None], deadline_s: float | None = None) -> dict[str, Any]:
    runner = p.runner
    started = time.monotonic()
    rec = evidence.new_record(p.to_json(), executor.backend.name,
                              executor.node if runner.kind == "node" else executor.python)
    rec["isolation"] = executor.workspace.summary() if executor.workspace else None
    rec["environment"] = env_key
    toolchain = "node" if runner.kind == "node" else "python"
    if executor.is_container:
        backend = executor.backend
        rec["image"] = {"ref": backend.images.get(toolchain, ""),  # type: ignore[attr-defined]
                        "digest": backend.image_digest(toolchain)}  # type: ignore[attr-defined]
    timings = cache.Timings(layout.state_dir, env_key)
    durations = {f: timings.file_s(f) or p.durations.get(f) for f in (p.universe_files or [s.test for s in p.selected])}
    ctx = _Ctx(root, layout, p, change, runner, toolchain, executor, workers, timeout_s, timeout_explicit, durations,
               timings, env_key, log)
    if deadline_s is not None:
        ctx.deadline = started + deadline_s
        rec["deadline_s"] = deadline_s
    # watchdog budgets: a file's own-process peak in this environment, else its `--record` time when
    # it was recorded in the same sandbox backend (traced, so slower), else none (the hard limit)
    same_backend = bool(p.durations_backend) and p.durations_backend == executor.backend.name
    ctx.watch_s = {f: timings.peak_s(f) or (p.durations.get(f) if same_backend else None) for f in durations}
    full_argv, not_runnable = _full_argv(runner)
    to_run = [s.test for s in p.selected if s.test not in p.duplicates]
    if p.duplicates:
        rec["not_run"] = [{"test": t, "reason": why} for t, why in sorted(p.duplicates.items())]
    decision = strategy.decide(runner, to_run, p.universe_files, durations,
                               full_required=p.full_suite_required, full_requested=full, workers=workers,
                               measured_full=timings.full_s, measured_startup=timings.startup_s,
                               full_runnable=bool(full_argv), targeted_ratio=timings.targeted_ratio,
                               full_unusable=timings.full_unusable)
    rec["strategy"] = decision.to_json()
    log(f"  strategy: {decision.kind}: {decision.reason}")
    rows: list[dict[str, Any]] = []
    if decision.kind == "full":
        rows = _run_full(ctx, rec, full_argv, decision)
    elif decision.kind == "targeted":
        batches = decision.batches
        multi = [b for b in batches if len(b) > 1]
        t_sel = time.monotonic()
        for chunk in run_parallel(lambda b: _run_batch(ctx, b), batches, workers):
            rows.extend(chunk)
        # calibrate on representative runs: most files passed (a failing import ends a file early),
        # nothing timed out, no file-by-file fallback
        passed = sum(1 for r in rows if r["status"] in {"pass", "no-tests"})
        if (decision.est_targeted_s and rows and passed >= 0.8 * len(rows) and not ctx.processes.get("rerun")
                and not any(r["status"] == "timeout" for r in rows)) or (decision.est_targeted_s and
                                                                        passed == len(rows) and rows):
            raw = decision.est_targeted_s / (timings.targeted_ratio or 1.0)
            timings.note_ratio((time.monotonic() - t_sel) / max(raw, 0.01))
        rec["execution"] = (f"{len(batches)} batch(es) of the {len(p.selected)} selected files, each in a fresh "
                            "copy; failing batches attributed per test, or re-run file by file" if multi else
                            "one process per selected file, each in a fresh copy")
    if decision.kind != "full" and (full or p.full_suite_required) and not full_argv:
        rec["full_suite"] = {"status": "not-run", "reason": not_runnable}
    rec["results"] = rows
    attribution_started = time.monotonic()
    _compare_with_base(ctx, rows)
    _check_skips(ctx, rows)
    rec["timing"] = {"total_s": round(time.monotonic() - started, 2),
                     "base_comparison_s": round(time.monotonic() - attribution_started, 2)}
    redundant = sum(n - 1 for n in ctx.file_runs.values() if n > 1)
    rec["processes"] = {"total": sum(ctx.processes.values()), **dict(sorted(ctx.processes.items())),
                        "test_file_runs_at_change": sum(ctx.file_runs.values()), "repeated_file_runs": redundant}
    timings.save()
    cut = ctx.deadline_hit
    rec["verdict"] = evidence.verdict(rec["results"], rec["full_suite"], len(p.selected), p.full_suite_required,
                                      behavioural=_behavioural(p),
                                      incomplete=f"the time budget of {deadline_s:g} s ran out before every test "
                                      "ran" if cut and deadline_s is not None else "")
    return rec


def _behavioural(p) -> bool:
    """The change can alter what a test observes: any changed file other than
    documentation that is not a comment-, formatting- or repo-ai-only edit."""
    return any(f.behavioral and f.kind != "docs" for f in p.files)


def _full_argv(runner: TestRunner) -> tuple[list[str], str]:
    """The full suite as argv, or ([], why it cannot be run here)."""
    argv = runner.full if runner.full else (shlex.split(runner.command) if runner.command else [])
    if not argv:
        return [], "no test command"
    from ..testing import instructable
    if not runner.full and not instructable(runner.command):
        return [], f"`{runner.command}` is not a plain test invocation; run it yourself"
    return argv, ""


def _full_cap(ctx: _Ctx) -> float:
    """The full suite's limit cap: an explicit `--timeout` as given (it used to
    become 1800 s here, so `--timeout 6` let a hanging full suite run for half
    an hour), otherwise at least half an hour."""
    return ctx.timeout_s if ctx.timeout_explicit else max(ctx.timeout_s, 1800.0)


def _run_full(ctx: _Ctx, rec: dict[str, Any], argv: list[str], decision: strategy.Decision) -> list[dict[str, Any]]:
    """The project's own full-suite command as one process. With a trusted
    per-test report, every test file gets its own result row (the selected
    ones, and any other file that failed); without one, the selection is
    run as well so the selected files still get per-file results."""
    p, runner = ctx.p, ctx.runner
    universe = p.universe_files if runner.per_file else []
    est = ctx.timings.full_s or decision.est_full_s
    limit = strategy.process_limit(est, _full_cap(ctx), ctx.timeout_explicit)
    ctx.log(f"  running the full suite: {runner.display(argv)}")
    res, att = _process(ctx, ctx.executor, argv, universe, limit, "full", count_files=bool(universe), native=True)
    status = _status(res)
    text = res.stderr + "\n" + res.stdout
    trusted = att is not None and att.trusted
    rec["full_suite"] = {"status": status, "exit_code": res.exit_code, "duration_s": round(res.duration_s, 2),
                         "command": runner.display(argv), "attributed": trusted or status == "pass",
                         "output_tail": evidence.failure_excerpt(text) if status != "pass" else ""}
    if status == "pass":
        ctx.timings.note_full(res.duration_s)
        if trusted and not ctx.timings.startup_s:
            _learn_from_batch(ctx, universe, res, att)
    selected = [s.test for s in p.selected]
    rec["execution"] = "the full suite as one process, in a fresh copy"
    if status == "pass":
        return [_row(ctx, f, NO_TESTS if trusted and att is not None and f in att.files and att.files[f].ran == 0
                     else "pass", res, argv, {}, "", shape="full", attributed=True,
                     duration=att.files[f].seconds if trusted and att is not None and f in att.files else 0.0)
                for f in selected]
    if trusted and att is not None:
        rec["full_suite"]["failing_files"] = att.failing_files()
        rows = []
        for f in sorted(set(selected) | set(att.failing_files())):
            fo = att.files[f]
            status_f = NO_TESTS if fo.status == "pass" and fo.ran == 0 else fo.status
            row = _row(ctx, f, status_f, res, argv, fo.failing, text, shape="full", attributed=True,
                       duration=fo.seconds)
            row["selected"] = f in set(selected)
            rows.append(row)
        return rows
    if not (runner.per_file and selected):
        return []
    if res.timed_out and att is not None and not att.unmapped:
        hung = [f for f in universe if f in att.files and att.files[f].hung]
        if hung:
            return _full_timed_out(ctx, rec, res, att, argv, text, limit, hung, selected)
    why = att.reason if att is not None else "this runner gives no per-test report"
    # a timeout means the change made something hang: it says nothing about whether this suite's
    # failures can be attributed, so the suite stays eligible for speed (held-out-5 h11 `mut-04`
    # turned every later run of that project into a slower targeted run)
    if not res.timed_out and not (p.full_suite_required or decision.reason.startswith("--full")):
        # chosen only because it was expected to be faster: the selection decides the verdict, and
        # this environment's full suite is not chosen for speed again (post-hoc, held-out-4 tomlkit:
        # a collection error stops the whole native pytest session, every time)
        rec["full_suite"]["advisory"] = True
        rec["full_suite"]["reason"] = f"not required; its failures cannot be attributed to files ({why})"
        ctx.timings.note_full_unusable(why)
    ctx.log(f"  the full suite failed and its failures cannot be attributed to files ({why}); "
            "running the selected files for per-file results")
    rec["execution"] += "; the selection was run as well because the full suite's failures could not be attributed"
    rows = []
    batches = strategy.make_batches(runner, [f for f in selected if f not in p.duplicates], ctx.durations,
                                    ctx.workers)
    for chunk in run_parallel(lambda b: _run_batch(ctx, b), batches, ctx.workers):
        rows.extend(chunk)
    return rows


def _full_timed_out(ctx: _Ctx, rec: dict[str, Any], res, att: results.Attribution, argv: list[str], text: str,
                    limit: float, hung: list[str], selected: list[str]) -> list[dict[str, Any]]:
    """The full suite hit its limit while a known test was running: that file
    is reported as timing out (it is not run again, which would cost the limit
    a second time), files that finished keep their results, and only the
    selected files that never started run again."""
    runner = ctx.runner
    reported = _node_reported(att) if runner.kind == "node" else set()
    finished = {f for f in att.files if f not in hung and (
        f in reported if runner.kind == "node" else att.complete(f))}
    ctx.log(f"  the full suite timed out after {limit:.0f}s in {', '.join(hung[:3])}; {len(finished)} file(s) "
            "had finished")
    rec["full_suite"]["timed_out_in"] = hung[:20]
    rec["full_suite"]["attributed"] = True  # the per-file rows below carry the outcome
    rows = []
    for f in hung:
        failures = {tid: _unfinished(res, limit) for tid in att.files[f].hung}
        failures.update(att.files[f].failing)
        row = _row(ctx, f, "timeout", res, argv, failures, text, shape="full", attributed=True,
                   duration=res.duration_s)
        row["selected"] = f in set(selected)
        rows.append(row)
    for f in sorted(finished & (set(selected) | set(att.failing_files()))):
        fo = att.files[f]
        row = _row(ctx, f, NO_TESTS if fo.status == "pass" and fo.ran == 0 else fo.status, res, argv, fo.failing,
                   text, shape="full", attributed=True, duration=fo.seconds, seconds=fo.test_seconds)
        row["selected"] = f in set(selected)
        rows.append(row)
    pending = [f for f in selected if f not in finished and f not in hung and f not in ctx.p.duplicates]
    if pending:
        rec["execution"] += f"; the {len(pending)} selected file(s) that had not started were run separately"
        for chunk in run_parallel(lambda b: _run_batch(ctx, b),
                                  strategy.make_batches(runner, pending, ctx.durations, ctx.workers), ctx.workers):
            rows.extend(chunk)
    return rows


# --------------------------------------------------------------------------
# base comparison
# --------------------------------------------------------------------------
MAX_IDS_PER_PROCESS = 300
MAX_CONFIRM = 25


def _base_files(root: Path, commit: str) -> set[str]:
    out = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "--end-of-options", commit], cwd=root,
                         capture_output=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    return {p for p in out.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


def _id_argv(runner: TestRunner, ids: list[str]) -> list[str]:
    if runner.kind == "unittest":
        return ["python", "-m", "unittest", *ids]
    return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *runner.options, *ids]


IDS_PER_GROUP = 25


def _split(items: list[Any], k: int) -> list[list[Any]]:
    """At most `k` groups, and no more than needed: a process per
    `IDS_PER_GROUP` items (a few failing tests share one process)."""
    k = max(1, min(k, -(-len(items) // IDS_PER_GROUP)))
    return [items[i::k] for i in range(k)] if items else []


@dataclass(slots=True)
class _BaseOutcome:
    check: str                                     # "per test" | "per file" | "full suite"
    failed: bool = False                           # the file (or one of its tests) failed at the base
    ids: set[str] = field(default_factory=set)     # failing test ids at the base
    missing: set[str] = field(default_factory=set)  # requested tests not defined at the base
    source: str = "run"                            # "run" | "cached" | "mixed"
    msgs: dict[str, str] = field(default_factory=dict)  # failing id -> its failure at the base (when run)


class _LazyBase:
    """The base revision's disposable workspace, created on first use."""

    def __init__(self, ctx: _Ctx):
        self.ctx = ctx
        self.ws: isolate.Workspace | None = None
        self.template: Executor | None = None

    def get(self) -> Executor:
        if self.template is None:
            try:
                self.ws = isolate.materialize_commit(self.ctx.root, self.ctx.change.base_commit)
            except isolate.IsolationError as exc:
                raise VerifyError(str(exc)) from exc
            self.template = self.ctx.executor.in_workspace(self.ws)
        return self.template

    def cleanup(self) -> None:
        if self.ws is not None:
            self.ws.cleanup()


def _compare_with_base(ctx: _Ctx, rows: list[dict[str, Any]]) -> None:
    """Which failures are new. A failure is compared with the base revision
    in the same shape it happened in:
    - from the full suite: the full suite at the base (one process; its per-
      file outcomes are cached for this base tree and environment);
    - otherwise each failing test alone at the base, all of them in at most
      `workers` processes (by test id when the runner can address single
      tests, else by file); a failure that came from a multi-file process
      and does not fail at the base is also re-run alone at the change, so a
      failure that only happens next to other files is reported as that,
      not as a regression.
    Base outcomes already known are taken from `cache.BaselineCache` (see its
    rules for when a cached failure may be used)."""
    failing = [r for r in rows if r["status"] not in {"pass", NO_TESTS}]
    reasons = {s.test: s for s in ctx.p.selected}
    for r in failing:
        sel = reasons.get(r["test"])
        r["linked_by"] = [x.to_json() for x in sel.reasons] if sel else []
    if not failing:
        return
    change = ctx.change
    if not change.base_commit:
        for r in failing:
            r["classification"] = "not compared with the base (the repository has no base commit)"
        return
    ctx.log("  checking failures against the base revision…")
    bc = cache.BaselineCache(ctx.layout.state_dir, ctx.env_key, cache.tree_of(ctx.root, change.base_commit))
    at_base = _base_files(ctx.root, change.base_commit)
    for r in failing:
        if r["test"] not in at_base:
            r["baseline"] = "absent"
    outcomes: dict[str, _BaseOutcome] = {}
    confirmed: dict[tuple[str, str], str] = {}
    base = _LazyBase(ctx)
    try:
        full_rows = [r for r in failing if r.get("shape") == "full" and r.get("baseline") != "absent"]
        if full_rows:
            _base_full(ctx, base, bc, full_rows, outcomes)
        rest = [r for r in failing if r.get("baseline") != "absent" and r["test"] not in outcomes]
        if rest:
            _base_alone(ctx, base, bc, rest, outcomes, confirmed)
    finally:
        base.cleanup()
        bc.save()
    deps = _dependencies_changed(change)
    for r in failing:
        _classify(r, outcomes.get(r["test"]), confirmed)
        if deps and r.get("baseline") == "fail" and not r.get("new_failing_tests"):
            r["baseline"] = "not-comparable"
            r["classification"] = (f"fails at the base too, but the change edits {', '.join(deps[:3])} and the base "
                                   "ran with the dependencies installed now: not comparable")


DEPENDENCY_NAMES = {"pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
                    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", ".python-version",
                    ".nvmrc", ".node-version"}


def _dependencies_changed(change: ch.Change) -> list[str]:
    """Changed files that declare dependencies. The base runs with the
    dependencies installed now (one environment for both), so with such a
    change a failure that also fails at the base may have the same cause in
    both runs: it cannot be called pre-existing."""
    out = []
    for f in change.files:
        name = PurePosixPath(f.path).name
        if name in DEPENDENCY_NAMES or (name.startswith("requirements") and name.endswith((".txt", ".in"))):
            out.append(f.path)
    return out


def _check_skips(ctx: _Ctx, rows: list[dict[str, Any]]) -> None:
    """A file that passed only because every test in it was skipped (or that
    now defines none) verified nothing. Run it at the base: if its tests
    ran there, the change made them skip, and the run does not count as a
    pass (`unverified`). Skipping there too (a platform-specific test, say)
    is reported but changes nothing."""
    cand = [r for r in rows if r.get("baseline") != "absent" and (
        r["status"] == NO_TESTS or (r["status"] == "pass" and (lambda t: t[0] > 0 and t[1] == t[0])(
            ctx.skips.get(r["test"], (0, 0)))))]
    if not cand or not ctx.change.base_commit:
        return
    at_base = _base_files(ctx.root, ctx.change.base_commit)
    cand = [r for r in cand if r["test"] in at_base][:MAX_CONFIRM]
    if not cand:
        return
    ctx.log(f"  {len(cand)} file(s) skipped every test (or defined none): checking whether their tests run "
            "at the base")
    base = _LazyBase(ctx)
    try:
        base.get()

        def one(r: dict[str, Any]) -> tuple[dict[str, Any], Any, Any]:
            f = r["test"]
            res, att = _process(ctx, base.get(), ctx.runner.file_argv(f), [f], _limit(ctx, [f]), "base",
                                count_files=False)
            return r, res, att
        for r, res, att in run_parallel(one, cand, ctx.workers):
            fo = att.files.get(r["test"]) if att is not None else None
            if res.timed_out:  # its tests may well run at the base: this file verified nothing
                r["unverified"] = ("every test is skipped with this change" if r["status"] == "pass" else
                                   "defines no test with this change") + \
                    "; whether they run at the base is unknown (the base run did not finish)"
                continue
            if fo is None:
                r["skip_check"] = "the base run could not tell (no per-test report)"
                continue
            ran = fo.tests - fo.skipped
            if ran > 0:
                r["unverified"] = (f"every test is skipped with this change, but {ran} ran at the base"
                                   if r["status"] == "pass" else
                                   f"defines no test with this change, but {ran} ran at the base")
            elif (ctx.runner.kind == "node" and r["status"] == NO_TESTS and fo.tests == 0 and res.exit_code == 0
                  and r.get("exit_code") == 0):
                # a script-style node test file (top-level asserts, no test() call), at both revisions: it ran
                # and exited 0 as before, which is all such a file can show
                r["status"] = "pass"
                r["skip_check"] = "a test file without test() calls at the base too: its exit status is the result"
            else:
                r["skip_check"] = "its tests are skipped at the base too"
    finally:
        base.cleanup()


def _base_full(ctx: _Ctx, base: _LazyBase, bc: cache.BaselineCache, rows: list[dict[str, Any]],
               outcomes: dict[str, _BaseOutcome]) -> None:
    """Failures of the full suite against the full suite at the base."""
    files = [r["test"] for r in rows]
    hits = {f: bc.get("full-file", f) for f in files}
    if all(h is not None for h in hits.values()):
        for f, h in hits.items():
            assert h is not None
            outcomes[f] = _BaseOutcome("full suite", h[0] == "fail", set(h[1]), source=bc.source("full-file", f))
        return
    argv, _ = _full_argv(ctx.runner)
    universe = ctx.p.universe_files
    est = ctx.timings.full_s
    limit = strategy.process_limit(est, _full_cap(ctx), ctx.timeout_explicit)
    ctx.log("  running the full suite at the base (once per base revision; the result is reused)")
    res, att = _process(ctx, base.get(), argv, universe, limit, "base", count_files=False, native=True)
    if not _usable(res, att):
        return  # compared test by test instead
    for f in universe:
        fo = att.files.get(f) if att is not None else None
        failed = fo is not None and fo.status != "pass"
        ids = set(fo.failing) if failed and fo is not None else set()
        bc.put("full-file", f, "fail" if failed else "pass", sorted(ids))
        if f in files:
            outcomes[f] = _BaseOutcome("full suite", failed, ids, msgs=dict(fo.failing) if failed and fo else {})


def _base_alone(ctx: _Ctx, base: _LazyBase, bc: cache.BaselineCache, rows: list[dict[str, Any]],
                outcomes: dict[str, _BaseOutcome], confirmed: dict[tuple[str, str], str]) -> None:
    runner = ctx.runner
    by_id: dict[str, dict[str, str]] = {}          # file -> {head id: base outcome pass|fail|absent}
    cached_ids: dict[str, int] = {}
    need_ids: list[tuple[str, str, str]] = []      # (file, head id, argv id)
    need_files: list[str] = []
    confirm: list[tuple[str, str, str]] = []
    seconds: dict[tuple[str, str], float] = {}
    id_msgs: dict[tuple[str, str], str] = {}
    for r in rows:
        f = r["test"]
        ids = list(r.get("failing_tests") or [])
        argv_ids = results.rerun_ids(runner, f, ids, "") if r["status"] == "fail" else None
        multi = bool(r.get("batched")) and runner.kind != "node"
        whole = bc.get("file", f)
        if whole is not None and whole[0] == "pass":
            # the whole file passes at the base, so each of its tests does
            outcomes[f] = _BaseOutcome("per file", False, set(), source=bc.source("file", f))
            if multi and argv_ids is not None and len(argv_ids) == len(ids):
                confirm += [(f, tid, aid) for tid, aid in zip(ids, argv_ids, strict=True)]
                seconds.update({(f, tid): float((r.get("failing_test_seconds") or {}).get(tid) or 1.0)
                                for tid in ids})
            continue
        if argv_ids is not None and len(argv_ids) == len(ids) and len(ids) <= MAX_IDS_PER_PROCESS:
            known: dict[str, str] = {}
            for tid, aid in zip(ids, argv_ids, strict=True):
                hit = bc.get("test", f"{f}::{tid}")
                if hit is not None:
                    known[tid] = hit[0]
                else:
                    need_ids.append((f, tid, aid))
            by_id[f] = known
            cached_ids[f] = len(known)
            if multi:
                confirm += [(f, tid, aid) for tid, aid in zip(ids, argv_ids, strict=True) if known.get(tid) != "fail"]
                seconds.update({(f, tid): float((r.get("failing_test_seconds") or {}).get(tid) or 1.0)
                                for tid in ids})
            continue
        if whole is not None:
            outcomes[f] = _BaseOutcome("per file", True, set(whole[1]), source=bc.source("file", f))
        else:
            need_files.append(f)
    jobs: list[tuple[str, Any]] = [("ids", g) for g in _split(need_ids, ctx.workers)]
    jobs += [("files", g) for g in strategy.make_batches(runner, need_files, ctx.durations, ctx.workers)]
    if len(confirm) > MAX_CONFIRM:
        # many failing tests are a regression, not order-dependence: every failure stays confirmed
        for r in rows:
            if r.get("batched"):
                r["confirmation"] = f"not re-run alone: {len(confirm)} failing tests (more than {MAX_CONFIRM})"
        confirm = []
    if confirm:
        jobs.append(("confirm", confirm))
    retry: list[str] = []
    if jobs:
        def run_job(job: tuple[str, Any]) -> tuple[str, Any, Any, Any]:
            kind, items = job
            if kind == "files":
                argvs = runner.group_argvs(items) if len(items) > 1 else [runner.file_argv(items[0])]
                if len(argvs) != 1:
                    return kind, items, None, None
                res, att = _process(ctx, base.get(), argvs[0], items, _limit(ctx, items), "base", count_files=False)
                return kind, items, res, att
            files = sorted({f for f, _, _ in items})
            template = ctx.executor if kind == "confirm" else base.get()
            limit = _limit(ctx, files)
            if kind == "confirm":  # the failing tests alone: a few times their own measured durations
                est = strategy.startup_estimate(ctx.durations, ctx.timings.startup_s) + sum(
                    seconds.get((f, tid), 1.0) for f, tid, _ in items)
                limit = strategy.process_limit(est, limit, ctx.timeout_explicit)
            res, att = _process(ctx, template, _id_argv(runner, list(dict.fromkeys(a for _, _, a in items))), files,
                                limit, "confirm" if kind == "confirm" else "base",
                                count_files=kind == "confirm", owners=_owners(items))
            return kind, items, res, att

        base.get()  # create it once, before the parallel jobs
        for kind, items, res, att in run_parallel(run_job, jobs, ctx.workers):
            if kind == "files":
                if res is None or (len(items) > 1 and not _usable(res, att)):
                    retry += items
                    continue
                for f in items:
                    o = _file_outcome(res, att, f)
                    if o is None:
                        continue  # not compared with the base
                    outcomes[f] = _BaseOutcome("per file", o[0] == "fail", o[1], msgs=_msgs(att, f))
                    bc.put("file", f, o[0], sorted(o[1]))
            elif kind == "ids":
                if not _usable(res, att):
                    # a name the base cannot resolve (pytest refuses the whole run), a crash: by file
                    for f in sorted({f for f, _, _ in items}):
                        by_id.pop(f, None)
                        if f not in retry and f not in outcomes:
                            retry.append(f)
                    continue
                for f, tid, _ in items:
                    if f not in by_id:
                        continue
                    fo = att.files.get(f) if att is not None else None
                    if fo is not None and tid in fo.missing:
                        by_id[f][tid] = "absent"
                    elif fo is not None and tid in fo.failing:
                        by_id[f][tid] = "fail"
                        id_msgs[(f, tid)] = fo.failing[tid]
                        bc.put("test", f"{f}::{tid}", "fail")
                    else:
                        by_id[f][tid] = "pass"
                        bc.put("test", f"{f}::{tid}", "pass")
            else:  # confirm: the failing tests alone, at the change
                usable = _usable(res, att)
                for f, tid, _ in items:
                    fo = att.files.get(f) if att is not None else None
                    # an unusable confirmation cannot clear a failure: it stays confirmed. One the time
                    # budget cut, or never started, says nothing either way: unknown
                    confirmed[(f, tid)] = ("unknown" if DEADLINE_NOTE in res.notes else
                                           "pass" if usable and not res.timed_out and fo is not None
                                           and tid not in fo.failing else "fail")
    if retry:
        def one(f: str) -> tuple[str, tuple[str, set[str]] | None]:
            res, att = _process(ctx, base.get(), runner.file_argv(f), [f], _limit(ctx, [f]), "base",
                                count_files=False)
            return f, _file_outcome(res, att, f)
        for f, o in run_parallel(one, retry, ctx.workers):
            if o is None:
                continue  # not compared with the base
            outcomes[f] = _BaseOutcome("per file", o[0] == "fail", o[1])
            bc.put("file", f, o[0], sorted(o[1]))
    for f, known in by_id.items():
        if f in outcomes:
            continue
        n = cached_ids.get(f, 0)
        outcomes[f] = _BaseOutcome("per test", any(o == "fail" for o in known.values()),
                                   {t for t, o in known.items() if o == "fail"},
                                   {t for t, o in known.items() if o == "absent"},
                                   source="cached" if n == len(known) else ("mixed" if n else "run"),
                                   msgs={t: m for (g, t), m in id_msgs.items() if g == f})


def _classify(r: dict[str, Any], o: _BaseOutcome | None, confirmed: dict[tuple[str, str], str]) -> None:
    f = r["test"]
    if r.get("baseline") == "absent":
        r["classification"] = "new test file failing"
        return
    if o is None:
        r["classification"] = "not compared with the base"
        return
    r["base_check"] = o.check
    r["baseline_source"] = o.source
    head = set(r.get("failing_tests") or []) - {"<file>"}
    whole = r["status"] == "timeout" or "<file>" in (r.get("failing_tests") or [])
    if not head and whole and o.failed and o.ids and "<file>" not in o.ids:
        # the file no longer completes (it hangs, or fails outside its tests: loading it, a fixture);
        # at the base it ran to the end with specific failures, so those cannot explain this
        r["baseline"] = "fail"
        r["new_failing_tests"] = ["<file>"]
        r["classification"] = ("new failure: the file " + ("times out" if r["status"] == "timeout" else
                               "fails outside its tests") + " with this change; at the base it ran to the end "
                               "(with other failures)")
        return
    if not head or (o.failed and not o.ids and o.check != "per test"):
        # no individual test to compare: the file's outcome decides
        r["baseline"] = "fail" if o.failed else "pass"
        r["classification"] = ("already failing at the base (individual tests not compared)" if o.failed
                               else "new failure: passes at the base, fails with this change")
        if not o.failed and r.get("batched") and confirmed.get((f, "<file>")) == "pass":
            r["confirmed"] = False
        if confirmed.get((f, "<file>")) == "unknown":
            r["deadline"] = True  # its confirmation was cut by the time budget: it shows nothing alone
        return
    new = sorted(head - o.ids)
    r["baseline"] = "fail" if o.failed and o.check != "per test" or head & o.ids else "pass"
    if r["baseline"] == "fail":
        r["new_failing_tests"] = new[:50]
    unconfirmed = [t for t in new if confirmed.get((f, t)) == "pass"]
    if unconfirmed:
        r["not_reproduced_alone"] = unconfirmed[:50]
    if new and len(unconfirmed) == len(new):
        r["confirmed"] = False
    if any(confirmed.get((f, t)) == "unknown" for t in new):
        r["deadline"] = True  # its confirmation was cut by the time budget: it shows nothing alone
    absent = [t for t in new if t in o.missing]
    changed = {t: {"base": o.msgs[t], "now": (r.get("failures") or {}).get(t, "")} for t in sorted(head & o.ids)
               if t in o.msgs and _norm(o.msgs[t]) != _norm((r.get("failures") or {}).get(t, ""))}
    if changed:
        # the same test fails at the base, but not the same way: the change may well have touched it
        r["changed_failures"] = dict(list(changed.items())[:20])
    if r["baseline"] == "fail" and new:
        r["classification"] = (f"new failures: {len(new)} test(s) fail with this change that pass at the base "
                               "(the file already had other failures)")
    elif r["baseline"] == "fail" and changed:
        r["classification"] = (f"already failing at the base, but {len(changed)} test(s) now fail differently "
                               "(the change may affect them; the base failure hides it)")
    elif r["baseline"] == "fail":
        r["classification"] = "already failing at the base (the same tests fail)"
    elif r.get("confirmed") is False:
        r["classification"] = ("fails only next to other test files: passes when re-run alone, at the change "
                               "and at the base (order-dependent or flaky)")
    elif absent and len(absent) == len(new):
        r["classification"] = "new test(s) failing (not defined at the base)"
    else:
        r["classification"] = "new failure: passes at the base, fails with this change"


_VOLATILE = re.compile(r"0x[0-9a-fA-F]+|\b\d+(?:\.\d+)?\s*(?:ms|s|sec|seconds)\b|at [^ ]+:\d+:\d+")


def _norm(msg: str) -> str:
    """A failure message without what differs between identical failures
    (object addresses, durations, stack positions)."""
    return _VOLATILE.sub("#", msg or "").strip()


def _msgs(att: results.Attribution | None, f: str) -> dict[str, str]:
    fo = att.files.get(f) if att is not None and att.trusted else None
    return dict(fo.failing) if fo is not None else {}


def _owners(items: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f, tid, _ in items:
        out.setdefault(tid, []).append(f)
    return out


def _usable(res, att: results.Attribution | None) -> bool:
    """A process whose per-test outcomes can be read: it passed outright, or
    its report is trusted."""
    return (res.exit_code == 0 and not res.timed_out) or (att is not None and att.trusted)


def _file_outcome(res, att: results.Attribution | None, f: str) -> tuple[str, set[str]] | None:
    """(pass | fail, failing ids) of one file at the base, or None when the
    base run says nothing: it was cut by the time limit, so a test that has
    not failed yet may still pass (a new failure would read as pre-existing)."""
    if res.timed_out:
        return None
    if (res.exit_code == 0 or (res.exit_code == _NO_TESTS_EXIT and not (
            att is not None and any(o.failing for o in att.files.values())))):
        return "pass", set()
    if att is not None and att.trusted:
        fo = att.files.get(f)
        return (fo.status, set(fo.failing)) if fo is not None else ("pass", set())
    return "fail", evidence.failing_tests(res.stderr + "\n" + res.stdout)


def _measure_full(root: Path, runner: TestRunner, bound: Executor, tmap: TestMap, timeout_s: float,
                  log: Callable[[str], None]) -> tuple[Any, results.Attribution | None, list[str]] | None:
    """The project's full-suite command once, untraced, as one process: the
    time a selection is compared with (`strategy`), and on a clean tree the
    base outcomes a full-suite failure is compared with."""
    argv, _ = _full_argv(runner)
    if not argv:
        return None
    universe = sorted(tmap.tests)
    total = sum(float(r.get("duration_s") or 0) for r in tmap.tests.values())
    limit = min(max(timeout_s, 1800.0), max(60.0, 2 * total))
    ex = bound.fresh()
    try:
        assert ex.workspace is not None
        report = None
        run_argv = argv
        if results.can_instrument(runner, argv):
            run_argv, report = results.instrument(runner, argv, ex.workspace.path, ex.inside_root, "full",
                                                  native=True)
        res = ex.run(run_argv, cwd=runner.cwd, env=runner.env, timeout_s=limit,
                     toolchain="node" if runner.kind == "node" else "python")
        att = (results.parse(report, runner, universe, ex.inside_root, exit_code=res.exit_code,
                             timed_out=res.timed_out) if report is not None else None)
    finally:
        release([ex])
    log(f"  measured the full suite as one process: {res.duration_s:.1f}s ({_status(res)}), for choosing how to "
        "run later changes")
    return res, att, universe


def record_evidence(root: Path, layout, executor: Executor, *, command: str | None = None,
                    workers: int = 4, timeout_s: float = 600.0,
                    log: Callable[[str], None] = lambda _: None,
                    command_source: str = "--test-command") -> TestMap:
    runner = establish_runner(root, layout, command, override_source=command_source)
    cmd = runner.command
    if not cmd:
        raise VerifyError("no trustworthy test command; pass --test-command")
    if not runner.per_file:
        raise VerifyError(f"`{cmd}` cannot be run per test file; runtime evidence needs unittest, "
                          "pytest or node --test")
    tests = runner.test_files(repo_files(root))
    if not tests:
        raise VerifyError("no test files found for the test command")
    change = ch.detect(root, "HEAD")
    before, ws, _ = _prepare(root, change, "record", log, layout=layout)
    full_run = None
    try:
        bound = executor.in_workspace(ws)
        tmap = record(root, runner, bound, tests, workers=workers, timeout_s=timeout_s, log=log)
        env_key = cache.environment_key(bound, runner)
        full_run = _measure_full(root, runner, bound, tmap, timeout_s, log)
    finally:
        ws.cleanup()
    integrity = _integrity(root, before)
    if not integrity["unchanged"]:
        raise SourceTreeChanged("the source tree changed while tests were recorded ("
                                + "; ".join(integrity["changes"][:3]) + "); nothing was saved")
    if full_run is not None and runner.kind == "pytest":
        res_f, att_f, _ = full_run
        if att_f is not None and att_f.done and not att_f.stopped and att_f.modules and not res_f.timed_out:
            # complete or nothing: every file whose tests ran must have been reported collected (with
            # xdist, workers forward only some collect reports: an incomplete list would leave real
            # test files out of the universe, and a broken change could then select nothing and pass)
            if complete_collection(att_f):
                tmap.collected = {"files": sorted(att_f.modules), "command": runner.command,
                                  "config": collection_config(root, repo_files(root), runner)}
            else:
                log("  pytest's collection report was incomplete; it is not used to decide which files are tests")
    tmap.uncommitted = sorted(f.path for f in change.files if f.behavioral)
    tmap.save(layout.state_dir / TESTMAP_NAME)
    clean = not tmap.uncommitted and bool(change.base_commit)
    if full_run is not None:
        res, att, universe = full_run
        timings = cache.Timings(layout.state_dir, env_key)
        if not res.timed_out and (res.exit_code == 0 or (att is not None and att.trusted)):
            timings.note_full(res.duration_s)  # what the cost model compares a selection with
            timings.save()
        if clean and _usable(res, att):
            bc = cache.BaselineCache(layout.state_dir, env_key, cache.tree_of(root, change.base_commit))
            for f in universe:
                fo = att.files.get(f) if att is not None else None
                failed = fo is not None and fo.status != "pass"
                bc.put("full-file", f, "fail" if failed else "pass", sorted(fo.failing) if failed and fo else [],
                       src="record")
            bc.save()
    if clean:
        # the recording ran the clean base revision file by file: each file that passed is a known
        # base pass for later comparisons (a cached pass can only make a failure look new, never hide one)
        bc = cache.BaselineCache(layout.state_dir, env_key, cache.tree_of(root, change.base_commit))
        for test, rec in tmap.tests.items():
            if rec.get("status") in {"pass", "no-tests"}:
                bc.put("file", test, "pass", src="record")
        bc.save()
    return tmap
