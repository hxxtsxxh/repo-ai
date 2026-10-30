"""Sealed hidden-oracle grader for abc-v5 (offline, deterministic, no model calls).

The grader never runs inside a candidate's workspace and never writes hidden tests into any directory a candidate (or
arm A) sees. Every grade builds three fresh throw-away trees:

  A-view   W (repo/ + acceptance/) + EVERY candidate file (test edits included); the task's test_command is run as a
           developer would. Green iff exit 0. This is arm A's decision, and the FALSE_GREEN criterion.
  frozen   W + only the candidate's write_paths files; every frozen W test ID (hidden/oracle.json) must PASS.
  hidden   a separate copy of the frozen tree + hidden/; every frozen oracle test ID must PASS.

Labels: CORRECT (frozen and hidden pass), FALSE_GREEN (not CORRECT, A-view green), FAIL (not CORRECT, A-view red),
INVALID (bad path / symlink / non-UTF-8 / oversize, timeout, flaky across repeats, or a harness error).

Improvements over abc-v4: per-test results (JUnit XML / TAP) instead of summary regexes; skipped or vanished expected
tests are not passes; expected test IDs are frozen, so a candidate cannot make oracle tests disappear; repeats must
agree (flake -> INVALID); strict candidate path validation; the A-view is graded separately from the frozen view, so
test tampering is visible rather than silently ignored; the grader refuses to run if the manifest seal is broken.

  python grade.py TASK CANDIDATE [--unsealed]     CANDIDATE is a name from tasks/TASK/candidates.json
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
TIMEOUT_S = 90
REPEATS = 2
MAX_FILE = 256_000
_SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*$")
_TAP = re.compile(r"^(ok|not ok) \d+ - (.*?)(?: # (SKIP|TODO)\b.*)?$")
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "node_modules", "map.json")


class SealBroken(RuntimeError):
    pass


class InvalidCandidate(ValueError):
    pass


def load_task(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "task.json").read_text())


def load_oracle(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "hidden" / "oracle.json").read_text())


def load_candidates(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "candidates.json").read_text())


def verify_seal() -> None:
    sys.path.insert(0, str(HERE))
    try:
        import make_manifest
    finally:
        sys.path.pop(0)
    problems = make_manifest.check(make_manifest.FULL_PATH) + make_manifest.check(make_manifest.W_PATH)
    if problems:
        raise SealBroken("; ".join(problems[:5]))


# ---------------------------------------------------------------- candidates
def validate_files(files: dict[str, str]) -> None:
    for rel, text in files.items():
        if not isinstance(rel, str) or not _SAFE.match(rel) or any(part in ("..", ".") for part in rel.split("/")):
            raise InvalidCandidate(f"unsafe path {rel!r}")
        if rel.split("/")[0] in (".git", ".repo-ai", "node_modules"):
            raise InvalidCandidate(f"reserved path {rel!r}")
        if not isinstance(text, str) or "\0" in text or len(text.encode("utf-8")) > MAX_FILE:
            raise InvalidCandidate(f"bad content for {rel!r}")


def read_dir(d: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(d.rglob("*")):
        if p.is_symlink():
            raise InvalidCandidate(f"symlink in candidate: {p.relative_to(d)}")
        if p.is_file() and "__pycache__" not in p.parts:
            try:
                out[str(p.relative_to(d)).replace("\\", "/")] = p.read_bytes().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise InvalidCandidate(f"non-UTF-8 file {p.name}") from exc
    return out


def candidate_files(task_id: str, name: str) -> dict[str, str]:
    c = load_candidates(task_id)[name]
    return {} if c["dir"] is None else read_dir(TASKS / task_id / c["dir"])


# ---------------------------------------------------------------- trees and suites
def materialize_w(task_id: str, dest: Path, acceptance: bool = True, extra_dirs: tuple[Path, ...] = ()) -> None:
    tdir = TASKS / task_id
    shutil.copytree(tdir / "repo", dest, ignore=_IGNORE)
    dirs = ((tdir / "acceptance",) if acceptance else ()) + tuple(extra_dirs)
    for d in dirs:
        for p in sorted(d.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.name != "map.json":
                rel = p.relative_to(d)
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest / rel)


def overlay(dest: Path, files: dict[str, str]) -> None:
    for rel, text in sorted(files.items()):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def scrubbed_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", NO_COLOR="1")
    return env


def test_files(task: dict, tree: Path) -> list[str]:
    pat = r"(^|/)test_[^/]*\.py$" if task["language"] == "python" else r"\.test\.(js|cjs|mjs)$"
    return sorted(str(p.relative_to(tree)).replace("\\", "/") for p in tree.rglob("*")
                  if p.is_file() and re.search(pat, str(p.relative_to(tree)).replace("\\", "/")))


def run_suite(task: dict, tree: Path, files: list[str] | None = None, developer: bool = False) -> dict:
    """Run the task's test runner in `tree`. files=None means discovery, exactly as a developer runs test_command.
    Returns {exit, tests: {id: pass|fail|skip}, error}. `developer` keeps the developer's interpreter flags (no -I)."""
    with tempfile.TemporaryDirectory(prefix="abc5-junit-") as jd:
        if task["language"] == "python":
            xml = Path(jd) / "r.xml"
            cmd = [sys.executable] + ([] if developer else ["-I"]) + [
                "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", "-o", "junit_family=xunit2"]
        else:
            cmd = ["node", "--test", "--test-reporter=tap"]
        cmd += list(files or [])
        try:
            p = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=TIMEOUT_S, env=scrubbed_env())
        except subprocess.TimeoutExpired:
            return {"exit": None, "tests": {}, "error": "timeout"}
        tests: dict[str, str] = {}
        if task["language"] == "python":
            if xml.is_file():
                for tc in ET.parse(xml).getroot().iter("testcase"):
                    tid = f"{tc.get('classname', '')}::{tc.get('name', '')}"
                    kids = {c.tag for c in tc}
                    tests[tid] = "fail" if kids & {"failure", "error"} else "skip" if "skipped" in kids else "pass"
        else:
            for line in p.stdout.splitlines():
                m = _TAP.match(line)
                if m:
                    tid = m.group(2).replace("\\#", "#")
                    tests[tid] = "skip" if m.group(3) else ("pass" if m.group(1) == "ok" else "fail")
        return {"exit": p.returncode, "tests": tests, "error": None}


def _repeat(fn, repeats: int) -> tuple[dict, bool]:
    runs = [fn() for _ in range(repeats)]
    first = runs[0]
    stable = all((r["exit"], r["tests"]) == (first["exit"], first["tests"]) for r in runs[1:])
    return first, stable


def _all_pass(observed: dict[str, str], expected: list[str]) -> tuple[bool, list[str]]:
    bad = [t for t in expected if observed.get(t) != "pass"]
    return not bad, bad


def _hashes(tree: Path) -> set[str]:
    return {hashlib.sha256(p.read_bytes()).hexdigest() for p in tree.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- grading
def grade(task_id: str, files: dict[str, str] | Path, *, repeats: int = REPEATS, sealed: bool = True,
          oracle: dict | None = None) -> dict:
    if sealed:
        verify_seal()
    task = load_task(task_id)
    tdir = TASKS / task_id
    oracle = oracle if oracle is not None else load_oracle(task_id)
    try:
        if isinstance(files, Path):
            files = read_dir(files)
        validate_files(files)
    except InvalidCandidate as exc:
        return {"task": task_id, "label": "INVALID", "reason": str(exc)}
    allowed = set(task["write_paths"])
    source = {k: v for k, v in files.items() if k in allowed}
    hidden_hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in (tdir / "hidden").rglob("*")
                     if p.is_file() and p.name != "oracle.json"}
    with tempfile.TemporaryDirectory(prefix="abc5-grade-") as tmp:
        root = Path(tmp)
        a_tree, f_tree, h_tree = root / "a", root / "f", root / "h"
        materialize_w(task_id, a_tree)
        overlay(a_tree, files)
        leak = bool(_hashes(a_tree) & hidden_hashes)
        a, a_stable = _repeat(lambda: run_suite(task, a_tree, None, developer=True), repeats)
        materialize_w(task_id, f_tree)
        overlay(f_tree, source)
        w_tests = test_files(task, f_tree)
        f, f_stable = _repeat(lambda: run_suite(task, f_tree, w_tests), repeats)
        materialize_w(task_id, h_tree)
        overlay(h_tree, source)
        hidden_rel = []
        for p in sorted((tdir / "hidden").rglob("*")):
            if p.is_file() and p.name != "oracle.json" and "__pycache__" not in p.parts:
                rel = p.relative_to(tdir / "hidden")
                shutil.copy2(p, h_tree / rel)
                hidden_rel.append(str(rel).replace("\\", "/"))
        h, h_stable = _repeat(lambda: run_suite(task, h_tree, hidden_rel), repeats)
    a_green = a["exit"] == 0
    f_ok, f_bad = _all_pass(f["tests"], oracle["visible_tests"])
    h_ok, h_bad = _all_pass(h["tests"], oracle["hidden_tests"])
    req_of = oracle.get("requirement_of", {})
    out = {"task": task_id, "ignored_paths": sorted(set(files) - allowed),
           "a_view": {"green": a_green, "exit": a["exit"], "tests": a["tests"]},
           "a_clean_green": f["exit"] == 0,
           "frozen": {"ok": f_ok, "not_passing": f_bad, "exit": f["exit"]},
           "hidden": {"ok": h_ok, "not_passing": h_bad, "exit": h["exit"]},
           "violated_requirements": sorted({req_of[t] for t in h_bad if t in req_of}),
           "hidden_leak_into_a_view": leak}
    errors = [x["error"] for x in (a, f, h) if x["error"]]
    if leak:
        out.update(label="INVALID", reason="hidden file content found in the A-view tree")
    elif errors:
        out.update(label="INVALID", reason="; ".join(errors))
    elif not (a_stable and f_stable and h_stable):
        out.update(label="INVALID", reason="results differ across repeats (flaky)")
    elif f_ok and h_ok:
        out["label"] = "CORRECT"
    elif a_green:
        out["label"] = "FALSE_GREEN"
    else:
        out["label"] = "FAIL"
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit("usage: grade.py TASK CANDIDATE [--unsealed]")
    tid, name = args
    print(json.dumps(grade(tid, candidate_files(tid, name), sealed="--unsealed" not in sys.argv), indent=2,
                     sort_keys=True))
