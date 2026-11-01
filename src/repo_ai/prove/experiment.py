"""One proof-of-change experiment: the pinned scenario at the base and at the
candidate, the base's own versions of edited tests against the candidate,
and the regression check, all sandboxed in disposable copies.

    pre  = preflight(root, layout, claim, base, runner)     # read-only
    pp   = run(root, layout, claim, base=..., executor=...) # runs repository code: needs authorization

Every run goes through ``verify.execute.Executor`` (no unsandboxed fallback)
and is read through ``verify.results`` (a report that is not trusted makes
the run incomplete, never passing). The source tree is snapshotted before and
checked after, as ``verify --run`` does.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .. import gitbin
from .. import __version__
from ..verify import changes as ch
from ..verify import engine, evidence, isolate, results
from ..verify.execute import Executor, release
from ..verify.runner import RunnerError, TestRunner
from ..verify.testmap import run_parallel
from . import claim as cl
from . import conditions, dataflow, passport

SUPPORTED_RUNNERS = ("unittest", "pytest", "node")
MAX_IDS = 200          # failure messages kept per run (display)
MAX_OUTCOMES = 5000    # test outcomes judged per run: more makes the run incomplete, never truncated
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\x1b]|\x9b|\x1b\[[0-9;?]*[ -/]*[@-~]")
# a scenario that cannot even load against the original code shows the interface is new, not that the
# original behaviour was wrong
STRUCTURAL = re.compile(r"^(?:\w+\.)*(?:ImportError|ModuleNotFoundError|SyntaxError|IndentationError|TabError)\b"
                        r"|cannot import name|does not provide an export named|Cannot find module|"
                        r"^AttributeError: module '[^']+' has no attribute|"
                        # a keyword, a parameter or a method the original code does not have (Session A's review P1);
                        # not an attribute missing on a value of a builtin type, which a wrong result can show
                        r"^TypeError: .*(?:got an unexpected keyword argument|takes (?:from )?\d+ (?:to \d+ )?"
                        r"positional arguments? but \d+ (?:were|was) given)|"
                        r"^AttributeError: (?:type object )?'(?!(?:NoneType|list|dict|str|int|float|tuple|set|bytes|"
                        r"bool)')[^']+' (?:object )?has no attribute|"
                        r"^TypeError: [\w.]+\(\) takes no (?:keyword )?arguments|"
                        r"^TypeError: (?:[\w.$]+ )?is not a (?:function|constructor)\b|"
                        r"ERR_MODULE_NOT_FOUND|ERR_PACKAGE_PATH_NOT_EXPORTED")


class ProveError(RuntimeError):
    pass


# credentials that appear bare, not as `key=value` (which `evidence.scrub` masks)
_BARE_SECRET = re.compile(r"(?i)\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|"
                          r"\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\bsk_(?:live|test)_[A-Za-z0-9]{10,}|"
                          r"\bxox[abprs]-[A-Za-z0-9-]{10,}|\bglpat-[A-Za-z0-9_-]{10,}|\bAIza[0-9A-Za-z_-]{20,}|"
                          r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|"
                          r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)|-----BEGIN [A-Z ]*PRIVATE KEY-----")
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")


def clean(text: str, limit: int = 300) -> str:
    """Untrusted test output, made safe to show: credentials masked, the home
    directory shortened to ~, control and escape sequences removed, one line,
    bounded."""
    text = _CONTROL.sub("", evidence.scrub(str(text or ""), 4 * limit))
    text = _BIDI.sub("", _BARE_SECRET.sub("<redacted>", text))
    home = str(Path.home())
    if len(home) > 1:  # the home directory itself, not a longer name that starts like it
        text = re.sub(re.escape(home) + r"(?=/|\\|\s|$|['\"])", "~", text)
    text = re.sub(r"/[^\s'\"]*repo-ai-ws[^\s'\"/]*", "<workspace>", text)
    return " ".join(text.split())[:limit]


def runner_identity(runner: TestRunner) -> dict[str, Any]:
    """What the scenario's command depends on (not the files it found)."""
    data = runner.to_json()
    return {k: data.get(k) for k in ("kind", "command", "cwd", "env", "options", "start", "top", "pattern",
                                     "modules", "paths")}


def runner_record(runner: TestRunner) -> dict[str, Any]:
    ident = runner_identity(runner)
    return {"kind": runner.kind, "command": runner.command, "source": runner.source,
            "identity_sha256": cl.sha256(repr(sorted(ident.items())).encode())}


# --------------------------------------------------------------------------
# preflight (read-only)
# --------------------------------------------------------------------------
def _tree_state(root: Path, rel: str, digest: str) -> str:
    p = root / rel
    if p.is_symlink():
        return "differs"
    if not p.is_file():
        return "absent"
    try:
        return "identical" if cl.sha256(p.read_bytes()) == digest else "differs"
    except OSError:
        return "differs"


def _base_state(root: Path, commit: str, rel: str, digest: str) -> str:
    res = subprocess.run([gitbin.git(), "cat-file", "blob", f"{commit}:{rel}"], cwd=root, capture_output=True,
                         timeout=60, check=False, stdin=subprocess.DEVNULL)
    if res.returncode != 0:
        return "absent"
    return "identical" if cl.sha256(res.stdout) == digest else "differs"


MAX_SUPPORT_DEPENDENTS = 40


def _glob(path: str, pattern: str) -> bool:
    """Path-aware: `*` and `?` stay within one directory, `**` crosses them;
    a pattern naming a directory covers everything below it."""
    pat = pattern.strip().rstrip("/")
    if path == pat or path.startswith(pat + "/"):
        return True
    rx = ""
    i = 0
    while i < len(pat):
        if pat.startswith("**", i):
            rx += ".*"
            i += 2
            if i < len(pat) and pat[i] == "/":
                i += 1
        elif pat[i] == "*":
            rx += "[^/]*"
            i += 1
        elif pat[i] == "?":
            rx += "[^/]"
            i += 1
        else:
            rx += re.escape(pat[i])
            i += 1
    return re.fullmatch(rx, path) is not None


def split_subject(change: ch.Change, scenario: str, record: dict[str, Any], files: list[str], read,
                  cwd: str = "") -> tuple[list[str], list[str], bool, list[str]]:
    """The change's code under test (its *subject*) and the rest of it.

    The scenario runs on the base plus the subject only, so nothing else the
    change edits (a fixture module, a plugin, a conftest.py, a helper, an
    expected value, a data file) can reach the scenario's run. The subject is
    what the claim declares (`--subject`), or else the changed files the
    scenario itself reaches through imports, test code, conftest files and
    modules of constants excepted. Returns (subject, the rest, declared)."""
    globs = record.get("subject") or []
    paths = sorted({p for f in change.files for p in (f.path, f.old_path) if p} - {scenario}
                   - {s["path"] for s in record.get("support") or []})
    present = set(files)
    reached = conditions.reachable(scenario, files, read, cwd)
    machinery, harness_reach = conditions.harness(files, read, cwd)

    def machinery_or_test(p: str) -> bool:
        """pytest's machinery, test code, or code only that machinery loads: never the code under test, even
        when a --subject glob covers it (a fixture module, a plugin)."""
        return p in machinery or PurePosixPath(p).name == "conftest.py" or conditions.testish(p, scenario, present) \
            or (p in harness_reach and p not in reached) or conditions.machinery_source(read(p))
    if globs:
        subject = [p for p in paths if any(_glob(p, g) for g in globs) and not machinery_or_test(p)]
        return subject, [p for p in paths if p not in subject], True, sorted(set(subject) | _code_edits(
            change, paths, machinery_or_test))
    deleted = {f.path for f in change.files if f.status == "deleted"} | {f.old_path for f in change.files
                                                                          if f.old_path}
    subject = []
    for p in paths:
        code = p.endswith(conditions.CODE_SUFFIXES)
        if not code or machinery_or_test(p):
            continue
        if p in deleted:
            subject.append(p)  # removed or moved code: its absence is part of the change
        elif p in reached and not (p.endswith(".py") and conditions.constants_only(read(p))):
            subject.append(p)
    # a renamed file keeps both of its paths together
    for f in change.files:
        if f.old_path and (f.path in subject) != (f.old_path in subject):
            subject = sorted(set(subject) | {f.path, f.old_path})
    return sorted(subject), [p for p in paths if p not in subject], False, sorted(set(subject) | _code_edits(
        change, paths, machinery_or_test))


# what a change may edit besides its code under test without making its regression check incomplete: the
# project's own configuration and lockfiles, at the root only
ROOT_CONFIG = frozenset({"pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", ".pytest.ini",
                         "MANIFEST.in", "Makefile", ".gitignore", ".gitattributes", ".editorconfig",
                         ".pre-commit-config.yaml", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock", "package.json",
                         "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "noxfile.py"})
TEST_DIRS = frozenset({"tests", "test", "__tests__"})


def checked_too(left_out: list[str], tests: set[str]) -> list[str]:
    """Edits `outside_subject` lets the claim keep (documentation, the root
    configuration, files in a test directory that are not collected tests):
    they still join the second regression tree, since code can read them
    (a `setup.cfg` section, a `docs/` text, a module under `mypkg/tests/`),
    so a base test that reads one shows the regression (the eighth review)."""
    strict = set(outside_subject(left_out, tests))
    return sorted(p for p in left_out if p not in strict and p not in tests and PurePosixPath(p).name != "conftest.py"
                  and not p.startswith(".repo-ai/"))


def outside_subject(left_out: list[str], tests: set[str]) -> list[str]:
    """What the change edits besides its code under test, its tests and their
    support (a collected test file, a `conftest.py`, anything in a `tests/`,
    `test/` or `__tests__/` directory), the documentation at the root or in
    `docs/`, and the root configuration (`ROOT_CONFIG`). Everything else
    counts, wherever it is and whatever it is named: code, data the code
    reads (`mypkg/banner.md`, `settings.ini`), a package named like test
    support (`mypkg/snapshots/`, `mypkg/testing.py`). The regression checks
    need it all checked against the base's own tests, or the claim is
    incomplete (Session A's S5, S17; the sixth and seventh reviews)."""
    out = []
    for p in left_out:
        pp = PurePosixPath(p)
        root_level = len(pp.parts) == 1
        if p in tests or pp.name == "conftest.py" or any(part in TEST_DIRS for part in pp.parts[:-1]) \
                or pp.parts[0] in {".repo-ai", ".github", "docs"} \
                or (root_level and (p in ROOT_CONFIG or p.lower().endswith(conditions.DOC_SUFFIXES)
                                    or pp.name.upper().startswith(conditions.DOC_NAMES))):
            continue
        out.append(p)
    return sorted(out)


def _code_edits(change: ch.Change, paths: list[str], machinery_or_test) -> set[str]:
    """Every code file of the change that is not test machinery or test code:
    what the subject-only check applies to the base, so that code the scenario
    does not reach is still run against the base's own tests."""
    return {p for p in paths if p.endswith(conditions.CODE_SUFFIXES) and not machinery_or_test(p)}


def edited_tests(change: ch.Change, base_tests: set[str], scenario: str, base_files: list[str] | None = None,
                 read_base=None, pinned: set[str] | None = None, cwd: str = "",
                 left_out: list[str] | None = None) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Test files that exist at the base and that the candidate modifies,
    renames or deletes, and base test files that depend on test support the
    candidate edits (a conftest.py, a helper or data under a test directory):
    their base versions, with the base's support files, are run against the
    candidate. Also returns the edited support files."""
    out: list[dict[str, Any]] = []
    for f in change.files:
        old = f.old_path or f.path
        if f.status in {"modified", "deleted", "renamed"} and old in base_tests:
            out.append({"path": old, "status": f.status, "is_scenario": str(old == scenario).lower()})
    present_base = set(base_files or [])
    # test support: a conftest.py or a file under a test directory the change edits, any file of the change left
    # out of the scenario's run (its subject excepted), and pinned support files, which existing tests may read too
    support = sorted({p for f in change.files for p in {f.old_path or f.path, f.path}
                      if p not in base_tests and p != scenario
                      and (p in (pinned or set()) or p in set(left_out or [])
                           or PurePosixPath(p).name == "conftest.py" or conditions.test_dir(p))})
    unmapped: list[str] = []
    if support and read_base is not None:
        listed = {r["path"] for r in out}
        # pytest loads its plugins for every test: what they reach is every test's dependency
        machinery, harness_reach = conditions.harness(base_files or [], read_base, cwd)
        everyone = machinery | harness_reach
        data = [s for s in support if not s.endswith(conditions.CODE_SUFFIXES)
                and not s.lower().endswith(conditions.DOC_SUFFIXES)
                and not PurePosixPath(s).name.upper().startswith(conditions.DOC_NAMES)]
        mapped: set[str] = set()
        for t in sorted(base_tests - listed):
            uses = [s for s in support if PurePosixPath(s).name == "conftest.py"
                    and (PurePosixPath(s).parent.as_posix() in {".", ""}
                         or t.startswith(PurePosixPath(s).parent.as_posix() + "/"))]
            if len(uses) < len(support):
                # what the test loads: its own imports, every conftest.py above it with what that reaches, and
                # pytest's plugins; the data files it (or that code) names
                deps = conditions.reachable(t, base_files or [], read_base, cwd) | everyone
                for d in conditions._ancestors(t):
                    c = f"{d}/conftest.py" if d else "conftest.py"
                    if c in present_base:
                        deps |= {c} | conditions.reachable(c, base_files or [], read_base, cwd)
                names = conditions.literal_names([t, *sorted(d for d in deps if conditions.testish(d, t, present_base)
                                                             or PurePosixPath(d).name == "conftest.py")],
                                                 read_base)
                uses += [s for s in support if s not in uses and (
                    s in deps or PurePosixPath(s).name in names
                    or (not s.endswith(conditions.CODE_SUFFIXES) and conditions.test_dir(s)
                        and conditions.test_dir(s) == conditions.test_dir(t)))]
                mapped |= set(uses)
            if uses:
                out.append({"path": t, "status": "uses edited test support", "is_scenario": "false",
                            "support": sorted(set(uses))})
        unmapped = [d for d in data if d not in mapped]
    return sorted(out, key=lambda r: r["path"]), support, unmapped


def preflight(root: Path, layout, record: dict[str, Any], base: str, runner: TestRunner) -> dict[str, Any]:
    """Everything an experiment checks before running anything: is the
    scenario the pinned one, are the oracle's conditions the same at both
    revisions, and what will run. Reads files and git objects only."""
    change = ch.detect(root, base)
    if not change.base_commit:
        raise ProveError("the repository has no commit to compare with; commit the original code first")
    scen = record["scenario"]
    rel = scen["path"]
    problems: list[dict[str, str]] = []
    own = {".gitignore"}  # what `repo-ai init` adds next to the code
    if not [f for f in change.files if f.path not in own and f.path != rel] and \
            _tree_state(root, rel, scen["sha256"]) != "differs":
        problems.append({"state": "incomplete", "why": (
            f"the working tree has no change against {base} ({change.base_commit[:12]}) besides the scenario: the "
            "candidate would be the original code. If the fix is already committed, compare with the commit before "
            f"it: --base {change.base_commit[:12]}~1")})
    if runner.kind not in SUPPORTED_RUNNERS:
        problems.append({"state": "environment-unavailable", "why": (
            f"the test runner is {runner.kind or 'unknown'} ({runner.command or 'no command'}); ProofLab runs "
            "unittest, pytest and node --test scenarios")})
    pinned_runner = record.get("runner") or {}
    now_runner = runner_record(runner)
    if pinned_runner and pinned_runner.get("identity_sha256") != now_runner["identity_sha256"]:
        problems.append({"state": "conditions-differ", "why": (
            f"the test command is {runner.command!r} now, but {pinned_runner.get('command')!r} when the claim was "
            "pinned; pin the claim again if the change is intended")})
    in_tree = _tree_state(root, rel, scen["sha256"])
    if in_tree == "differs":
        problems.append({"state": "scenario-changed", "why": (
            f"{rel} in the working tree is not the pinned scenario (sha256 {scen['sha256'][:12]}): the candidate "
            "changed the acceptance test after it was pinned")})
    support = []
    for s in record.get("support") or []:
        st = _tree_state(root, s["path"], s["sha256"])
        support.append({"path": s["path"], "sha256": s["sha256"], "in_candidate_tree": st,
                        "in_base_tree": _base_state(root, change.base_commit, s["path"], s["sha256"])})
        if st == "differs":
            problems.append({"state": "scenario-changed", "why": (
                f"{s['path']} in the working tree is not the pinned support file (sha256 {s['sha256'][:12]})")})
    files = engine.repo_files(root)
    base_files, read_base = conditions.base_reader(root, change.base_commit)
    try:
        tests_cand = set(runner.test_files(files, root)) if runner.kind in SUPPORTED_RUNNERS else set()
        tests_base = set(runner.test_files(base_files, root)) if runner.kind in SUPPORTED_RUNNERS else set()
    except RunnerError:
        tests_cand = tests_base = set()
    pinned_paths = {rel, *(s["path"] for s in record.get("support") or [])}
    changed = {p for f in change.files for p in (f.path, f.old_path) if p}
    data = cl.load_blob(layout.state_dir, scen["sha256"])
    oracle = conditions.oracle_report(root, rel, runner.kind, change.base_commit, files, tests_base, tests_cand,
                                      pinned_paths, changed, scenario_bytes=data, cwd=runner.cwd)
    gitlinks = subprocess.run([gitbin.git(), "ls-files", "-s"], cwd=root, capture_output=True, text=True, timeout=60,
                              check=False, stdin=subprocess.DEVNULL).stdout
    if (root / ".gitmodules").is_file() or any(line.startswith("160000 ") for line in gitlinks.splitlines()):
        problems.append({"state": "environment-unavailable", "why": (
            "the repository has git submodules: the base copy (git archive) would leave out their content, so the "
            "base and the candidate would not run under the same conditions")})
    attrs = sorted({p for p in [*files, *base_files] if PurePosixPath(p).name == ".gitattributes"})
    rewritten = [p for p in attrs if re.search(rb"(?m)\bexport-(?:ignore|subst)\b",
                                               (conditions.tree_reader(root)(p) or b"") + (read_base(p) or b""))]
    if rewritten:
        problems.append({"state": "environment-unavailable", "why": (
            "the repository's " + ", ".join(rewritten[:3]) + " marks files export-ignore or export-subst: the base "
            "copies (git archive) would leave them out or rewrite them, so the base would not be the base")})
    shadow = conditions.shadows([f.path for f in change.files if f.status != "deleted"])
    if shadow:
        problems.append({"state": "conditions-differ", "why": (
            "the candidate adds or changes files that could replace the test machinery itself: "
            + ", ".join(shadow[:5]) + " (a module named like pytest, unittest or sitecustomize, or a .pth file)")})
    if not oracle["identical"]:
        problems.append({"state": "conditions-differ", "why": (
            "the candidate changes files that decide how the scenario runs: " + ", ".join(oracle["differing"][:5])
            + (" …" if len(oracle["differing"]) > 5 else "") + "; pin them with --support so both runs use the same "
            "bytes, or keep them unchanged")})
    try:
        argv = runner.file_argv(rel) if runner.kind in SUPPORTED_RUNNERS else []
    except RunnerError as exc:
        argv = []
        problems.append({"state": "environment-unavailable", "why": f"the scenario cannot be run by itself: {exc}"})
    def cand_read(p: str, _tree=conditions.tree_reader(root)) -> bytes | None:
        return data if p == rel else _tree(p)
    subject, left_out, declared, _ = split_subject(change, rel, record, files, cand_read, runner.cwd)
    outside = outside_subject(left_out, tests_base | tests_cand)
    code_edits = sorted(set(subject) | set(outside) | set(checked_too(left_out, tests_base | tests_cand)))
    if not subject:
        problems.append({"state": "incomplete", "why": (
            "the change edits no file the scenario reaches (no code under test): the scenario would run on the "
            "original code at both sides. Declare the code under test with `prove pin --subject PATH`")})
    edited, edited_support, unmapped_data = edited_tests(change, tests_base, rel, base_files, read_base,
                                                         pinned_paths, runner.cwd, left_out=left_out)
    # what the scenario's candidate side runs: the base plus the subject (and the pinned files)
    ran = set(base_files) | set(subject) | pinned_paths
    def ran_read(p: str) -> bytes | None:
        return cand_read(p) if p in set(subject) | pinned_paths else read_base(p)
    abstain = dataflow.findings(rel, runner.kind, ran, ran_read, set(subject), runner.cwd,
                                read_base=read_base) if subject else []
    if subject and not declared:
        abstain.insert(0, "the code under test was inferred from what the change edits, not declared when the claim "
                          "was pinned (`prove pin --subject`): the change would choose its own subject, so the claim "
                          "is not supported (the eighth review)")
    if len(edited) > MAX_SUPPORT_DEPENDENTS:
        problems.append({"state": "incomplete", "why": (
            f"{len(edited)} existing test files are edited or depend on edited test support ("
            + ", ".join(edited_support[:3]) + "): more than ProofLab re-runs with their base versions ("
            f"{MAX_SUPPORT_DEPENDENTS}); keep the test support unchanged, or prove a smaller change")})
    return {
        "change": change, "base_tests": tests_base, "argv": argv,
        "scenario": {**{k: scen[k] for k in ("path", "sha256", "bytes", "provenance")},
                     "in_candidate_tree": in_tree,
                     "in_base_tree": _base_state(root, change.base_commit, rel, scen["sha256"]),
                     "notes": conditions.scenario_notes(data, runner.kind)},
        "support": support, "runner": now_runner, "oracle": oracle,
        "edited_tests": edited, "edited_support": edited_support, "unmapped_data": unmapped_data,
        "subject": {"declared": declared, "files": subject[:200], "left_out": left_out[:200],
                    "code_edits": code_edits[:500], "outside": outside[:500]},
        "abstain": abstain,
        "command": runner.display(argv) if argv else "",
        "problems": problems,
    }


# --------------------------------------------------------------------------
# running one scenario process
# --------------------------------------------------------------------------
def _inject(ws: isolate.Workspace, rel: str, data: bytes) -> None:
    """Put pinned bytes at `rel` in a disposable copy: a checked relative
    path, through no link, created anew, and inside the copy."""
    rel = cl.norm_path(rel)
    top = ws.path.resolve()
    cur = top
    for part in PurePosixPath(rel).parent.parts:
        cur = cur / part
        if cur.is_symlink() or (cur.exists() and not cur.is_dir()):
            raise ProveError(f"cannot place {rel} in the copy: {cur.relative_to(top)} is not a directory")
    dst = top / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if top not in dst.parent.resolve().parents and dst.parent.resolve() != top:
        raise ProveError(f"cannot place {rel} in the copy: it would land outside it")
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    if rel not in ws.files:
        ws.files.append(rel)


# A test file that must fail, run in the same process as the scenario (unittest, pytest): code under test
# that disables the assertion machinery when it is imported (patching TestCase.assert*, the result
# object or pytest's reporting) makes one of these pass, and the run is then not trusted.
_CANARY_PY = """import unittest


class Check{tok}(unittest.TestCase):
    def test_{tok}_a(self):
        self.assertEqual(1, 2)

    def test_{tok}_b(self):
        self.assertTrue(False)

    def test_{tok}_c(self):
        with self.assertRaises(ValueError):
            pass

    def test_{tok}_d(self):
        assert [1] == [2]

    def test_{tok}_e(self):
        self.fail("{tok}")
"""
# appended to the scenario's copy for node (each file runs in its own process, so a separate canary file
# would not share the scenario's process); one form for ES modules and one for CommonJS
_CANARY_NODE_ESM = """
import {{ test as t{tok} }} from 'node:test';
import a{tok} from 'node:assert';
for (const [n, f] of [['a', () => a{tok}.equal(1, 2)], ['b', () => a{tok}.strictEqual(1, 2)],
                      ['c', () => a{tok}.deepStrictEqual([1], [2])], ['d', () => a{tok}.ok(false)],
                      ['e', () => a{tok}.throws(() => {{}})]]) t{tok}('{tok} ' + n, f);
"""
_CANARY_NODE_CJS = """
;(() => {{ const t{tok} = require('node:test'); const a{tok} = require('node:assert');
for (const [n, f] of [['a', () => a{tok}.equal(1, 2)], ['b', () => a{tok}.strictEqual(1, 2)],
                      ['c', () => a{tok}.deepStrictEqual([1], [2])], ['d', () => a{tok}.ok(false)],
                      ['e', () => a{tok}.throws(() => {{}})]]) t{tok}('{tok} ' + n, f); }})();
"""
CANARY_TESTS = 5


def canary_token() -> str:
    """A fresh name for every experiment: code that recognises a fixed canary could spare it."""
    import secrets
    return "c" + secrets.token_hex(5)


def node_canary(rel: str, files: list[str], read, data: bytes = b"") -> str | None:
    """The canary to append to a node scenario, or None (TypeScript, or a
    module type that cannot be told)."""
    suffix = PurePosixPath(rel).suffix
    if suffix in {".mjs"}:
        esm = True
    elif suffix in {".cjs"}:
        esm = False
    elif suffix == ".js":
        kind = ""
        for d in conditions._ancestors(rel):
            pkg = f"{d}/package.json" if d else "package.json"
            if pkg in files:
                import json as _json
                try:
                    kind = str((_json.loads((read(pkg) or b"{}").decode("utf-8", "replace")) or {}).get("type") or "")
                except (ValueError, AttributeError):
                    return None
                break
        if kind:
            esm = kind == "module"
        else:  # no "type": node decides by the file's own syntax
            esm = bool(re.search(rb"(?m)^\s*(?:import\s[^(]|import\{|export\s)", read(rel) or data or b""))
    else:
        return None
    return _CANARY_NODE_ESM if esm else _CANARY_NODE_CJS


def canary_path(rel: str, taken: set[str], tok: str) -> str:
    """Next to the scenario, named after it: unittest discovery from a nested
    top level runs one pattern, `<scenario stem>*.py`, which then matches the
    scenario and the canary (and must match nothing else: see `_argv`)."""
    p = PurePosixPath(rel)
    cand = (p.parent / f"{p.stem}_{tok}.py").as_posix()
    if cand in taken:
        raise ProveError("no free name for the canary next to the scenario")
    return cand


def _argv(runner: TestRunner, rel: str, canary: str, siblings: set[str]) -> list[str] | None:
    """One invocation that runs the scenario and the canary together, or None."""
    argvs = runner.group_argvs([rel, canary])
    if len(argvs) == 1:
        return argvs[0]
    argv = runner.file_argv(rel)
    if runner.kind != "unittest" or "-p" not in argv:
        return None
    import fnmatch
    stem = PurePosixPath(rel).stem
    pattern = f"{stem}*.py"
    folder = PurePosixPath(rel).parent.as_posix()
    others = [f for f in siblings if PurePosixPath(f).parent.as_posix() == folder and f not in {rel, canary}
              and fnmatch.fnmatch(PurePosixPath(f).name, pattern)]
    if others:
        return None
    i = argv.index("-p")
    return [*argv[:i + 1], pattern, *argv[i + 2:]]


def _drop(ws: isolate.Workspace, rel: str) -> None:
    """Remove `rel` from a disposable copy (a file the change added, left out
    of a run), never through a link."""
    rel = cl.norm_path(rel)
    dst = ws.path.resolve() / rel
    if ws.path.resolve() not in dst.parent.resolve().parents and dst.parent.resolve() != ws.path.resolve():
        raise ProveError(f"cannot remove {rel} from the copy: it is outside it")
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    if rel in ws.files:
        ws.files.remove(rel)


def _base_blob(root: Path, commit: str, rel: str) -> bytes | None:
    res = subprocess.run([gitbin.git(), "cat-file", "blob", f"{commit}:{rel}"], cwd=root, capture_output=True, timeout=60,
                         check=False, stdin=subprocess.DEVNULL)
    return res.stdout if res.returncode == 0 else None


def _outcomes(report: Path, runner: TestRunner, files: list[str], inside_root: str
              ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, set[str]]]]:
    """file -> test id -> pass | fail | skip, from the process's own report
    (read as untrusted, bounded, through `results`); and per file the ids
    that were expected failures (`xfail`) or modules that failed to load
    (`load`)."""
    events, _ = results._events(report)
    mapper = results._Mapper(runner, files, inside_root)
    out: dict[str, dict[str, str]] = {f: {} for f in files}
    flags: dict[str, dict[str, set[str]]] = {"xfail": {f: set() for f in files}, "load": {f: set() for f in files}}
    for ev in events:
        if ev.get("e") != "end" or ev.get("file") is True or ev.get("suite") is True or ev.get("collect") is True \
                or ev.get("sub"):
            continue
        tid = ev.get("id")
        o = ev.get("o")
        f = mapper.file(ev)
        if f in out and isinstance(tid, str) and o in {"pass", "fail", "error", "skip"}:
            tid = clean(tid, 1000)
            # an expected failure verifies nothing: like a skip
            out[f][tid] = "fail" if o == "error" else ("skip" if ev.get("xfail") is True else str(o))
            if ev.get("xfail") is True:
                flags["xfail"][f].add(tid)
            if ev.get("load") is True:  # a module that failed to import: no test ran there (contract §4 rule 2)
                flags["load"][f].add(tid)
    return out, flags


def run_once(template: Executor, runner: TestRunner, rel: str, timeout_s: float, label: str,
             canary: str = "", siblings: set[str] | None = None, node_tok: str = "") -> dict[str, Any]:
    """`rel` (with the canary, when given) in one process, in a fresh clone
    of the template's copy, reporting per-test outcomes."""
    ex = template.fresh()
    files = [rel, canary] if canary else [rel]
    try:
        assert ex.workspace is not None
        both = _argv(runner, rel, canary, siblings or set()) if canary else None
        if both is None:  # the runner cannot put both in one process: no canary
            files, canary = [rel], ""
        argv = both or runner.file_argv(rel)
        report = None
        run_argv = argv
        if results.can_instrument(runner, argv):
            run_argv, report = results.instrument(runner, argv, ex.workspace.path, ex.inside_root, label)
        res = ex.run(run_argv, cwd=runner.cwd, env=runner.env, timeout_s=timeout_s, toolchain=runner.language)
        att = (results.parse(report, runner, files, ex.inside_root, exit_code=res.exit_code, timed_out=res.timed_out)
               if report is not None else None)
        by_file, flags = _outcomes(report, runner, files, ex.inside_root) if report is not None else ({}, {})
    finally:
        release([ex])
    fo = att.files.get(rel) if att is not None else None
    failures = {clean(tid, 1000): clean(msg) for tid, msg in sorted((fo.failing if fo else {}).items())[:MAX_IDS]}
    per_id = dict(by_file.get(rel) or {})
    for tid in (fo.failing if fo else {}):
        per_id[clean(tid, 1000)] = "fail"
    hung = sorted(clean(t, 1000) for t in fo.hung)[:MAX_IDS] if fo else []
    trusted = bool(att is not None and att.trusted)
    reason = "" if trusted else (att.reason if att is not None else "this runner invocation cannot report per-test "
                                 "outcomes, so its result cannot be checked")
    if len(per_id) > MAX_OUTCOMES:
        trusted, reason = False, f"more than {MAX_OUTCOMES} test outcomes: too many to judge"
    if res.timed_out:
        reason = f"did not finish within {timeout_s:.0f}s (--timeout)" + (f": {reason}" if reason else "")
        if hung:
            reason += f"; still running: {hung[0]}"
    check = "not-applicable"
    if node_tok and att is not None:  # the canary tests appended to the scenario's own copy
        mine = {t for t in per_id if t.startswith(node_tok + " ")}
        survived = sorted(t for t in mine if per_id[t] != "fail")
        check = "tampered" if survived else ("ok" if len(mine) >= CANARY_TESTS else "missing")
        for t in mine:
            per_id.pop(t, None)
            failures.pop(t, None)
        if check != "ok" and trusted:
            trusted = False
            reason = ("tests that must fail passed in the scenario's process: the code under test may disable "
                      "assertions (" + ", ".join(survived[:2]) + ")") if survived else \
                "the assertion canary did not run in the scenario's process"
    if canary and att is not None:
        co = by_file.get(canary) or {}
        cf = att.files.get(canary)
        failed = set(cf.failing) if cf else set()
        survived = sorted(t for t, o in co.items() if o != "fail" and t not in failed)
        check = "tampered" if survived else ("ok" if len(failed) >= CANARY_TESTS else "missing")
        if check != "ok" and trusted:
            trusted = False
            reason = ("tests that must fail passed in the scenario's process: the code under test may disable "
                      "assertions (" + ", ".join(survived[:2]) + ")") if survived else \
                "the assertion canary did not run in the scenario's process"
    return {"exit_code": res.exit_code, "timed_out": res.timed_out, "seconds": round(res.duration_s, 2),
            "trusted": trusted, "reason": reason, "tests": fo.tests if fo else 0, "skipped": fo.skipped if fo else 0,
            "outcomes": dict(sorted(per_id.items())[:MAX_OUTCOMES]), "failures": failures, "hung": hung, "canary": check,
            "command": runner.display(argv),
            "expected_failures": len((flags.get("xfail") or {}).get(rel) or ()),
            "load_failures": sorted((flags.get("load") or {}).get(rel) or ())[:MAX_IDS],
            "report": {"present": report is not None and att is not None and att.reason != "no per-test report was "
                                                                                           "written",
                       "complete": bool(att is not None and att.done)},
            "stdout_sha256": cl.sha256(res.stdout.encode("utf-8", "replace")),
            "stderr_sha256": cl.sha256(res.stderr.encode("utf-8", "replace"))}


# --------------------------------------------------------------------------
# reading the observations
# --------------------------------------------------------------------------
def _consistent(runs: list[dict[str, Any]]) -> bool:
    return len({tuple(sorted(r["outcomes"].items())) for r in runs}) <= 1


def judge_baseline(runs: list[dict[str, Any]], targets: list[str], expect: str | None) -> dict[str, Any]:
    """Did the original code show the targeted failure, the same way every time?"""
    out: dict[str, Any] = {"repeats": runs, "targets_failing": [], "kind": ""}
    bad = [r for r in runs if not r["trusted"]]
    if bad:
        return {**out, "state": "incomplete", "why": "the scenario's run at the base is incomplete: " + bad[0]["reason"]}
    if not _consistent(runs):
        return {**out, "state": "incomplete",
                "why": "the scenario's outcome at the base differed between repeats (flaky or order-dependent)"}
    first = runs[0]
    failing = sorted(t for t, o in first["outcomes"].items() if o == "fail")
    if targets:
        missing = [t for t in targets if t not in first["outcomes"]]
        if missing and "<file>" not in failing:
            seen = sorted(first["outcomes"])
            close = [t for t in seen if missing[0] in t or t.endswith(missing[0].split(".")[-1].split("::")[-1])]
            return {**out, "state": "not-reproduced", "why": (
                f"pinned target {missing[0]!r} is not a test id the scenario reported at the base"
                + (f"; did you mean {close[0]!r}?" if close else "")
                + " (ids it reported: " + ", ".join(seen[:5]) + (" …" if len(seen) > 5 else "") + ")")}
        passed = [t for t in targets if first["outcomes"].get(t) in {"pass", "skip"}]
        if passed:
            return {**out, "state": "not-reproduced",
                    "why": f"pinned target {passed[0]!r} "
                           + ("passed" if first["outcomes"][passed[0]] == "pass" else "was skipped") + " at the base"}
    if not failing:
        return {**out, "state": "not-reproduced",
                "why": "every test of the scenario passed at the base: it does not show the original failure"}
    focus = [t for t in failing if not targets or t in targets or t == "<file>"]
    msgs = {t: first["failures"].get(t, "") for t in focus}
    if expect:
        rx = re.compile(expect)
        if not all(any(rx.search(r["failures"].get(t, "")) for t in focus) for r in runs):
            return {**out, "state": "not-reproduced", "targets_failing": focus, "kind": "unexpected",
                    "why": "the base failed, but not with the pinned failure (--expect-failure): "
                           + (next(iter(msgs.values()), "") or "no message")[:160]}
        return {**out, "state": "reproduced", "targets_failing": focus, "kind": "matches-pinned-failure",
                "why": "the base fails as pinned"}
    if all(t == "<file>" or STRUCTURAL.search(m or "") for t, m in msgs.items()):
        return {**out, "state": "load-failure", "targets_failing": focus, "kind": "load",
                "why": "the scenario cannot load against the original code ("
                       + (next(iter(msgs.values()), "") or "a load error")[:160] + "): that shows an interface is new, "
                       "not that the original behaviour was wrong. Pin --expect-failure if this is the claim"}
    return {**out, "state": "reproduced", "targets_failing": focus, "kind": "behaviour",
            "why": f"{len(focus)} targeted test(s) fail at the base"}


def judge_candidate(runs: list[dict[str, Any]], base_runs: list[dict[str, Any]], targets_failing: list[str],
                    targets: list[str] | None = None) -> dict[str, Any]:
    """Does the candidate pass every test of the same scenario, the same way every time?"""
    out: dict[str, Any] = {"repeats": runs, "failing": []}
    failing = sorted({t for r in runs if r["trusted"] for t, o in r["outcomes"].items() if o == "fail"})
    if failing and all(r["trusted"] for r in runs):
        return {**out, "state": "failed", "failing": failing,
                "why": f"{len(failing)} test(s) of the scenario fail at the candidate: {failing[0]}"
                       + (f" ({runs[0]['failures'].get(failing[0], '')[:120]})" if runs[0]["failures"].get(failing[0])
                          else "")}
    bad = [r for r in runs if not r["trusted"]]
    if bad:
        return {**out, "state": "incomplete", "failing": failing,
                "why": "the scenario's run at the candidate is incomplete: " + bad[0]["reason"]}
    if not _consistent(runs):
        return {**out, "state": "incomplete",
                "why": "the scenario's outcome at the candidate differed between repeats (flaky or order-dependent)"}
    first = runs[0]
    if not first["outcomes"] or all(o == "skip" for o in first["outcomes"].values()):
        return {**out, "state": "incomplete", "why": "no test of the scenario ran at the candidate"}
    for t in sorted(set(targets_failing) | set(targets or [])):  # pinned targets always, whatever the base showed
        if t == "<file>":
            continue
        o = first["outcomes"].get(t)
        if o is None:
            return {**out, "state": "incomplete", "why": f"targeted test {t!r} did not run at the candidate"}
        if o == "skip":
            return {**out, "state": "incomplete", "why": f"targeted test {t!r} was skipped at the candidate"}
    base_ran = {t for r in base_runs for t, o in r["outcomes"].items() if o != "skip"}
    newly_skipped = sorted(t for t, o in first["outcomes"].items() if o == "skip" and t in base_ran)
    if newly_skipped:
        return {**out, "state": "incomplete",
                "why": f"{len(newly_skipped)} test(s) that ran at the base are skipped at the candidate: "
                       + newly_skipped[0]}
    return {**out, "state": "passed", "why": f"all {len(first['outcomes'])} test(s) of the scenario pass"}


def judge_shipped(subject_side: dict[str, Any], shipped: dict[str, Any], subj: dict[str, Any]) -> dict[str, Any]:
    """The scenario's candidate judgement, given the same scenario on the
    whole working tree as the change ships it: the claim holds only when both
    pass, the same way. A file the subject leaves out (a package's
    `__init__.py`, data the code reads) can restore the bug in what ships."""
    out = {**subject_side, "shipped": shipped}
    if subject_side["state"] != "passed":
        return out
    left = ", ".join((subj.get("left_out") or [])[:3]) or "files outside the code under test"
    if shipped["state"] == "failed":
        return {**out, "state": "failed", "failing": shipped.get("failing") or [], "why": (
            "the candidate as shipped (the whole working tree) fails the scenario, while the base plus the code under "
            f"test passes it: the change's other edits ({left}) change the result. " + shipped["why"])}
    if shipped["state"] != "passed":
        return {**out, "state": "incomplete", "why": "the scenario's run on the whole working tree: " + shipped["why"]}
    a = (subject_side.get("repeats") or [{}])[0].get("outcomes") or {}
    z = (shipped.get("repeats") or [{}])[0].get("outcomes") or {}
    if a != z:
        diff = sorted(t for t in set(a) | set(z) if a.get(t) != z.get(t))
        return {**out, "state": "incomplete", "why": (
            "the scenario's outcome on the whole working tree differs from the base plus the code under test ("
            + ", ".join(diff[:3]) + f"): the change's other edits ({left}) reach the scenario")}
    return out


def merge_code_check(ed: dict[str, Any], wide: dict[str, Any]) -> dict[str, Any]:
    """The subject-only check, joined with the same suite on the base plus
    every code edit: a regression either tree shows is detected."""
    out = {**ed, "code_edits_check": {k: wide.get(k) for k in ("state", "why", "files")}}
    if wide["state"] == "detected":
        have = {r["path"] for r in ed.get("files") or []}
        rows = list(ed.get("files") or []) + [{**r, "with_all_code_edits": True} for r in wide.get("files") or []
                                             if r["path"] not in have and r.get("new_failures")]
        return {**out, "state": "detected", "files": sorted(rows, key=lambda r: r["path"])}
    if wide["state"] == "incomplete" and ed["state"] == "none-detected":
        return {**out, "state": "incomplete", "why": "the check on the base plus every code edit is incomplete: "
                + str(wide.get("why", ""))}
    return out


def run_suite(template: Executor, runner: TestRunner, files: list[str], timeout_s: float, label: str
              ) -> dict[str, Any]:
    """The project's full suite, as one process in a fresh clone of the
    template's copy, with per-test outcomes keyed `file :: test`."""
    argv, why = engine._full_argv(runner)
    if not argv:
        return {"trusted": False, "reason": why or "no full-suite command", "outcomes": {}, "failures": {}}
    ex = template.fresh()
    try:
        assert ex.workspace is not None
        report = None
        run_argv = argv
        if results.can_instrument(runner, argv):
            run_argv, report = results.instrument(runner, argv, ex.workspace.path, ex.inside_root, label, native=True)
        res = ex.run(run_argv, cwd=runner.cwd, env=runner.env, timeout_s=timeout_s, toolchain=runner.language)
        att = (results.parse(report, runner, files, ex.inside_root, exit_code=res.exit_code, timed_out=res.timed_out)
               if report is not None else None)
        by_file, _flags = _outcomes(report, runner, files, ex.inside_root) if report is not None else ({}, {})
    finally:
        release([ex])
    outcomes: dict[str, str] = {}
    failures: dict[str, str] = {}
    for f, ids in by_file.items():
        for t, o in ids.items():
            outcomes[f"{f} :: {t}"] = o
    for f, fo in (att.files.items() if att is not None else []):
        for t, msg in fo.failing.items():
            outcomes[f"{f} :: {clean(t, 1000)}"] = "fail"
            failures[f"{f} :: {clean(t, 1000)}"] = clean(msg)
    trusted = bool(att is not None and att.trusted) and len(outcomes) <= 20 * MAX_OUTCOMES
    reason = "" if trusted else (att.reason if att is not None and att.reason else
                                 "the full suite could not report per-test outcomes")
    if res.timed_out:
        reason = f"the full suite did not finish within {timeout_s:.0f}s"
        trusted = False
    return {"trusted": trusted, "reason": reason, "outcomes": outcomes, "failures": failures,
            "seconds": round(res.duration_s, 2), "exit_code": res.exit_code}


def judge_suite(base: dict[str, Any], subject: dict[str, Any], supersedes: list[str]) -> dict[str, Any]:
    """New failures of the existing tests when only the code under test
    changes: tests that do not fail at the base and fail on the base plus the
    subject. `supersedes`: test ids whose old expectation the change replaces
    on purpose."""
    if not (base["trusted"] and subject["trusted"]):
        bad = base if not base["trusted"] else subject
        return {"state": "incomplete", "files": [], "why": "the subject-only check is incomplete: " + bad["reason"]}
    new = sorted(k for k, o in subject["outcomes"].items() if o == "fail" and base["outcomes"].get(k) != "fail")
    # a test that ran at the base and is absent or skipped now has stopped checking anything: never a pass
    gone = sorted(k for k, o in base["outcomes"].items()
                  if o != "skip" and subject["outcomes"].get(k, "skip") == "skip")
    superseded = [k for k in new if k.split(" :: ", 1)[-1] in supersedes]
    new = [k for k in new if k not in superseded]
    rows: dict[str, dict[str, Any]] = {}
    for k in [*new, *gone]:
        f, _, t = k.partition(" :: ")
        row = rows.setdefault(f, {"path": f, "state": "detected", "new_failures": [], "superseded": [],
                                  "messages": {}})
        row["new_failures"].append(t if k in new else f"{t} (no longer runs)")
        row["messages"][t] = subject["failures"].get(k, "")
    for k in superseded:
        f, _, t = k.partition(" :: ")
        rows.setdefault(f, {"path": f, "state": "none-detected", "new_failures": [], "superseded": [],
                            "messages": {}})["superseded"].append(t)
    files = sorted(rows.values(), key=lambda r: r["path"])
    detected = any(r["new_failures"] for r in files)
    return {"state": "detected" if detected else "none-detected", "files": files,
            "tests": len(base["outcomes"]), "seconds": [base.get("seconds"), subject.get("seconds")]}


def judge_edited(pairs: list[dict[str, Any]], supersedes: list[str]) -> dict[str, Any]:
    """The base's own versions of edited test files, at the base and at the
    candidate: a test that passed at the base and fails at the candidate is
    behaviour the change altered while also editing its test."""
    rows, detected, incomplete = [], [], []
    for p in pairs:
        b, c = p["base"], p["candidate"]
        row = {"path": p["path"], "status": p["status"], "new_failures": [], "superseded": []}
        if not (b["trusted"] and c["trusted"]):
            row["state"] = "incomplete"
            row["why"] = (b if not b["trusted"] else c)["reason"]
            incomplete.append(row)
        else:
            base_fail = {t for t, o in b["outcomes"].items() if o == "fail"}
            cand_fail = {t for t, o in c["outcomes"].items() if o == "fail"}
            new = sorted(cand_fail - base_fail)
            row["superseded"] = [t for t in new if t in supersedes]
            row["new_failures"] = [t for t in new if t not in supersedes]
            row["messages"] = {t: c["failures"].get(t, "") for t in row["new_failures"][:20]}
            row["state"] = "detected" if row["new_failures"] else "none-detected"
            if row["new_failures"]:
                detected.append(row)
        rows.append(row)
    state = "detected" if detected else ("incomplete" if incomplete else ("none-detected" if rows else "none-edited"))
    return {"state": state, "files": rows}


def judge_regressions(rec: dict[str, Any] | None, error: str, requested: bool) -> dict[str, Any]:
    if not requested:
        return {"state": "not-checked", "why": "the regression check was not requested (--no-regressions)"}
    if rec is None:
        return {"state": "incomplete", "why": "the regression check did not complete: " + (error or "no result")}
    from ..verify import report
    summ = report.summarize(rec)
    verdict = str(rec.get("verdict") or "")
    plan_info = rec.get("plan") or {}
    info = {"verdict": verdict, "fingerprint": rec.get("fingerprint"), "evidence": rec.get("path"),
            "new_failures": summ["new_failures"][:20], "pre_existing": summ["pre_existing"][:20],
            "passed": summ["passed"], "selected": len(rec.get("selected") or []),
            "test_files_total": plan_info.get("test_files_total"), "confidence": plan_info.get("confidence"),
            "full_suite": (rec.get("full_suite") or {}).get("status") if rec.get("full_suite") else "not-run",
            "reused": bool(rec.get("reused"))}
    if verdict.startswith("nothing-selected"):  # no test ran: it shows nothing (the contract's §6, 1.1)
        return {**info, "state": "incomplete", "why": "verify selected no test for this change: nothing was checked"}
    if evidence.is_passing(verdict):
        return {**info, "state": "none-detected", "why": f"verify: {verdict}"}
    if verdict == "regression":
        return {**info, "state": "detected", "why": "verify found new failures in existing tests"}
    if verdict.startswith("failing (all failures pre-existing at the base)"):
        return {**info, "state": "none-detected", "why": "verify: no new failures; some tests already fail at the base"}
    return {**info, "state": "incomplete", "why": f"verify: {verdict}"}


# --------------------------------------------------------------------------
# the experiment
# --------------------------------------------------------------------------
def environment(executor: Executor, runner: TestRunner, root: Path) -> dict[str, Any]:
    """The sandbox and tool versions (the interpreter is asked with -I -S, so
    no repository code or site hook runs on the host)."""
    def version(argv: list[str]) -> str:
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False,
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return (out.stdout or out.stderr).strip().splitlines()[0][:80] if (out.stdout or out.stderr).strip() else \
            "unknown"
    env: dict[str, Any] = {"repo_ai": __version__, "backend": executor.backend.name, "os": platform.system(),
                           "os_release": platform.release(), "machine": platform.machine(),
                           "platform": platform.platform(terse=True)}
    if executor.is_container:
        images = getattr(executor.backend, "images", {}) or {}
        env["image"] = str(images.get(runner.language, ""))
        try:
            env["image_digest"] = str(executor.backend.image_digest(runner.language))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - identity by reference only
            env["image_digest"] = "unknown"
    elif runner.language == "node":
        # a version-manager shim (asdf, mise, nvm-style) obeys the repository's version file: never run either
        env["node"] = "unknown (inside the repository: not executed on the host)" if _in_repo(executor.node, root) \
            else "unknown (a version-manager shim: not executed on the host)" if "shims" in _resolved_parts(
                executor.node) else clean(version([executor.node, "--version"]), 40)
    else:
        env["python"] = python_version(executor.python, root)
    return env


def _resolved_parts(path: str) -> tuple[str, ...]:
    try:
        return Path(path).resolve().parts
    except OSError:
        return ("shims",)  # cannot tell: treated as a launcher, never run


def _in_repo(path: str, root: Path) -> bool:
    """verify's own test (`execute._inside`): by directory identity, so
    another spelling of the repository (case on macOS) is still inside it."""
    from ..verify.execute import _inside
    return _inside(root, Path(path))


def python_version(python: str, root: Path) -> str:
    """The interpreter's version, without executing a file that lives in the
    repository (a committed `.venv/bin/python` is the repository's code):
    then it is read from the virtualenv's `pyvenv.cfg`, as text."""
    exe = Path(python)
    if _in_repo(python, root):
        for cfg in (exe.parent.parent / "pyvenv.cfg",):
            try:
                for line in cfg.read_text("utf-8", "replace").splitlines()[:50]:
                    key, _, value = line.partition("=")
                    if key.strip() in {"version", "version_info"} and value.strip():
                        return clean(value.strip(), 40) + " (from pyvenv.cfg)"
            except OSError:
                pass
        return "unknown (the interpreter is inside the repository and is not executed on the host)"
    try:
        out = subprocess.run([python, "-I", "-S", "-c", "import sys;print(sys.version.split()[0])"],
                             capture_output=True, text=True, timeout=20, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return clean(out.stdout.strip(), 40) or "unknown"


def run(root: Path, layout, record: dict[str, Any], *, base: str, runner: TestRunner, executor: Executor | None,
        repeat: int = 2, timeout_s: float = 300.0, workers: int = 4, regressions: bool = True,
        regression_run: Callable[[], dict[str, Any]] | None = None, sandbox_error: str = "", keep_going: bool = False,
        suite_timeout_s: float = 600.0,
        log: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    """Run the experiment and record its passport. Runs repository code (in
    the sandbox): the caller must hold the user's authorization.
    `regression_run`: runs `verify --run` for this change and returns its
    evidence record (the CLI passes `engine.run_plan`)."""
    started = time.monotonic()
    pre = preflight(root, layout, record, base, runner)
    change: ch.Change = pre["change"]
    pp = passport.new(record, pre, base, change)
    if executor is None:
        pre["problems"].insert(0, {"state": "environment-unavailable", "why": sandbox_error or "no sandbox"})
    else:
        pp["environment"] = environment(executor, runner, root)
    if pre["problems"]:  # nothing runs when the experiment would not be a comparison
        return passport.finish(layout.state_dir, pp, problems=pre["problems"], seconds=time.monotonic() - started)
    assert executor is not None
    env_key = env_key_for(root, executor, runner)
    pp["environment"]["key"] = env_key
    rel = pre["scenario"]["path"]
    data = cl.load_blob(layout.state_dir, record["scenario"]["sha256"])
    support = [(s["path"], cl.load_blob(layout.state_dir, s["sha256"])) for s in record.get("support") or []]
    workspaces: list[isolate.Workspace] = []
    log(f"  scenario {rel} (sha256 {record['scenario']['sha256'][:12]}), {repeat} run(s) at the base "
        f"{change.base_commit[:12]} and at the candidate, in the {executor.backend.name} sandbox")
    try:
        # the whole working tree, as the change ships it: the scenario must pass there too (Session A's S1, S2d,
        # S5: a file the subject leaves out can restore the bug)
        before, shipped_ws, _semantic = engine._prepare(root, change, "prove", log, layout=layout)
        workspaces.append(shipped_ws)
        base_orig = isolate.materialize_commit(root, change.base_commit, label="prove-base")
        workspaces.append(base_orig)
        # the candidate side of the scenario: the base plus only the change's code under test (its subject), so
        # no other edit of the change (a fixture, a plugin, a conftest.py, an expected value) reaches the run
        def with_code(ws: isolate.Workspace, paths: list[str]) -> None:
            for path in paths:
                here = root / path
                if here.is_file() and not here.is_symlink():
                    _inject(ws, path, here.read_bytes())
                else:
                    _drop(ws, path)
        # the scenario's candidate side: the base plus the subject only
        cand = base_orig.clone("prove-cand")
        workspaces.append(cand)
        with_code(cand, pre["subject"]["files"])
        # the subject-only check's tree: the base plus the subject, and nothing else of the change
        subject_ws = base_orig.clone("prove-subject")
        workspaces.append(subject_ws)
        with_code(subject_ws, pre["subject"]["files"])
        # the second regression tree: the base plus every edit of the change but its tests and their support,
        # its docs and root configuration, so that what it edits outside the subject (code, data, a production
        # module named like a test helper) runs against the base's own tests too (Session A's S5, S17)
        outside = list(pre["subject"]["outside"])
        code_ws = None
        if set(pre["subject"]["code_edits"]) - set(pre["subject"]["files"]):
            code_ws = base_orig.clone("prove-code")
            workspaces.append(code_ws)
            with_code(code_ws, pre["subject"]["code_edits"])
        for ws in (cand, shipped_ws):
            for path, blob in [(rel, data), *support]:
                _inject(ws, path, blob)
        canary, node_tok, tok = "", "", canary_token()
        canary_bytes = b""
        if runner.kind in {"unittest", "pytest"}:
            canary = canary_path(rel, set(cand.files) | set(shipped_ws.files)
                                 | set(conditions.base_reader(root, change.base_commit)[0]), tok)
            canary_bytes = _CANARY_PY.format(tok=tok).encode()
            for ws in (cand, shipped_ws):
                _inject(ws, canary, canary_bytes)
        elif runner.kind == "node":
            suffix = node_canary(rel, engine.repo_files(root), conditions.tree_reader(root), data)
            if suffix is not None:  # the same bytes at both sides: the pinned scenario, then the canary
                node_tok = tok
                data = data + suffix.format(tok=tok).encode()
                for ws in (cand, shipped_ws):
                    _inject(ws, rel, data)
        base_ws = base_orig.clone("prove-base-s")
        workspaces.append(base_ws)
        # the negative control: a second, independent copy of the base (its own `git archive`)
        control_ws = isolate.materialize_commit(root, change.base_commit, label="prove-control")
        workspaces.append(control_ws)
        for ws in (base_ws, control_ws):
            for path, blob in [(rel, data), *support] + ([(canary, canary_bytes)] if canary else []):
                _inject(ws, path, blob)
        ex_cand, ex_base = executor.in_workspace(cand), executor.in_workspace(base_ws)
        # one job per side: its repeats run one after another (the contract's §7), each in a fresh clone;
        # the sides run in parallel. The control is a side like the others (§7, 1.1)
        sides: list[tuple[str, Executor, str, int]] = [("control", executor.in_workspace(control_ws), rel, repeat),
                                                       ("baseline", ex_base, rel, repeat),
                                                       ("candidate", ex_cand, rel, repeat),
                                                       ("shipped", executor.in_workspace(shipped_ws), rel, repeat)]

        def job(j: tuple[str, Executor, str, int]) -> list[tuple[str, str, dict[str, Any]]]:
            kind, ex, path, times = j
            out = []
            for i in range(times):
                obs = run_once(ex, runner, path, timeout_s, f"prove-{kind}-{i}",
                               canary=canary if kind in {"baseline", "candidate", "control", "shipped"} else "",
                               node_tok=node_tok if kind in {"baseline", "candidate", "control", "shipped"} else "",
                               siblings=set(ex.workspace.files) if ex.workspace is not None else set())
                log(f"  {kind:16s} {path}: {_short(obs)}")
                out.append((kind, path, obs))
            return out
        done = [row for rows in run_parallel(job, sides, workers) for row in rows]
        base_runs = [o for k, _, o in done if k == "baseline"]
        cand_runs = [o for k, _, o in done if k == "candidate"]
        control_runs = [o for k, _, o in done if k == "control"]
        shipped_runs = [o for k, _, o in done if k == "shipped"]
        # the control is the base too: it must agree with the base's own runs
        b = judge_baseline(base_runs + control_runs, record.get("targets") or [], record.get("expect_failure"))
        b["repeats"], b["control"] = base_runs, control_runs
        c = judge_candidate(cand_runs, base_runs, b["targets_failing"], record.get("targets") or [])
        c = judge_shipped(c, judge_candidate(shipped_runs, base_runs, b["targets_failing"], record.get("targets") or []),
                          pre["subject"])
        decided = c["state"] != "passed" or b["state"] != "reproduced"
        ed = {"state": "not-checked", "files": [], "why": "the scenario stage decided first"}
        if regressions and (not decided or keep_going):
            # the existing tests, all of them, on the base and on the base plus only the code under test: every other
            # edit of the change (helpers, fixtures, plugins, data, edited tests) is absent, so none can hide a
            # regression the code under test causes
            log("  subject-only check: the full suite on the base and on the base plus the code under test")
            suite_files = sorted(pre["base_tests"])
            ex_b, ex_s = executor.in_workspace(base_orig), executor.in_workspace(subject_ws)
            trees = [(ex_b, "suite-base"), (ex_s, "suite-subject")]
            if code_ws is not None:
                more = sorted(set(pre["subject"]["code_edits"]) - set(pre["subject"]["files"]))
                log("  and on the base plus every edit of the change (" + ", ".join(more[:3])
                    + (" …" if len(more) > 3 else "") + " outside the code under test)")
                trees.append((executor.in_workspace(code_ws), "suite-code"))
            pair = run_parallel(lambda j: run_suite(j[0], runner, suite_files, suite_timeout_s, j[1]), trees,
                                len(trees))
            ed = judge_suite(pair[0], pair[1], record.get("supersedes") or [])
            if code_ws is not None:
                ed = merge_code_check(ed, judge_suite(pair[0], pair[2], record.get("supersedes") or []))
            if outside and ed["state"] == "none-detected":
                # what the change edits outside the subject ran against the base's tests only next to the change's
                # other edits, which could hide what it breaks (an expected value in a module named like code, a data
                # file and the test reading it): whether a file is code or an expected value cannot be told from it
                ed = {**ed, "state": "incomplete", "why": (
                    "the change edits files outside its code under test (" + ", ".join(outside[:3])
                    + (" …" if len(outside) > 3 else "") + "): code, or data that code may read; declare them with "
                    "`prove pin --subject` so that they run against the base's own tests, or leave them out of the "
                    "change")}
    finally:
        for ws in workspaces:
            ws.cleanup()
    integrity = engine._integrity(root, before)
    subj = pre["subject"]
    if c["state"] in {"failed", "incomplete"} and subj["left_out"] and not subj["declared"]:
        c["why"] += ("; the scenario ran without the change's edits to " + ", ".join(subj["left_out"][:3])
                     + ": if they are part of the fix, declare the code under test with `prove pin --subject`")
    rec, error = None, ""
    skip = ("the scenario stage already shows the claim is not established (--keep-going runs the regression check "
            "anyway)") if decided and not keep_going else ""
    if regressions and integrity["unchanged"] and not skip:
        log("  regression check: verify --run on the same change")
        try:
            rec = regression_run() if regression_run is not None else None
        except engine.SourceTreeChanged as exc:
            error = str(exc)
            integrity = {**integrity, "unchanged": False, "changes": [*integrity.get("changes", []), "during the "
                                                                                                  "regression check"]}
        except (engine.VerifyError, isolate.IsolationError, ch.ChangeError, RunnerError) as exc:
            error = str(exc)
    reg = judge_regressions(rec, error or ("not run: the source tree changed" if not integrity["unchanged"] else ""),
                            regressions) if not (skip and regressions) else {"state": "not-checked", "why": skip}
    try:  # the change itself must still be the one the experiment ran
        if ch.fingerprint(root, base) != change.fingerprint:
            integrity = {**integrity, "unchanged": False,
                         "changes": [*integrity.get("changes", []), "the working tree changed during the experiment"]}
    except ch.ChangeError:
        pass
    from . import contract
    host_python = not executor.is_container and runner.language == "python"
    evidence_in = {"sides_raw": {"base": base_runs, "candidate": cand_runs, "control": control_runs,
                                 "shipped": shipped_runs},
                   "runner_identity": runner_identity(runner),
                   "argv": sorted({o["command"] for o in base_runs + cand_runs + control_runs + shipped_runs}),
                   "env_key": env_key, "caps": contract.cap_conditions(root, change, executor.python, host_python),
                   "full_suite_passed": (rec or {}).get("full_suite") is not None
                   and ((rec or {}).get("full_suite") or {}).get("status") == "pass",
                   "integrity_ok": bool(integrity["unchanged"]), "tree": _rev(root, f"{change.base_commit}^{{tree}}"),
                   "head": _rev(root, "HEAD")}
    return passport.finish(layout.state_dir, pp, baseline=b, candidate=c, edited=ed, regressions=reg,
                           integrity=integrity, seconds=time.monotonic() - started, runner=runner, repeat=repeat,
                           evidence_in=evidence_in, abstain=pre.get("abstain") or [])


def _rev(root: Path, rev: str) -> str:
    out = subprocess.run([gitbin.git(), "rev-parse", "--verify", "--quiet", "--end-of-options", rev], cwd=root,
                         capture_output=True, text=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    return out.stdout.strip()


def env_key_for(root: Path, executor: Executor, runner: TestRunner) -> str:
    """verify's environment key (the contract's freshness condition)."""
    from ..verify import cache
    listing = isolate.worktree_files(root)
    links = {r: str((root / r).resolve()) for r in isolate.dependency_dirs(root, listing[0])}
    return cache.environment_key(executor, runner, links=links)


def _short(obs: dict[str, Any]) -> str:
    if not obs["trusted"]:
        return "incomplete (" + obs["reason"][:80] + ")"
    fails = sum(1 for o in obs["outcomes"].values() if o == "fail")
    return f"{len(obs['outcomes']) - fails} passed, {fails} failed ({obs['seconds']:.1f}s)"

