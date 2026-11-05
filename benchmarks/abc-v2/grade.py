"""Hidden-grader for the abc-v2 study. Grades the *actual* candidate files.

The grader never runs inside the agent's workspace: it copies the task's
``repo/`` into a throw-away directory, overlays only the candidate files that
are inside the task's ``write_paths`` (anything else is ignored and reported),
adds the hidden tests there, and runs visible and hidden tests separately.

Outcome vocabulary (preregistered in manifest.json):
  CORRECT        visible and hidden tests all pass
  FALSE_GREEN    visible pass, hidden fail (plausible-but-wrong patch)
  FAIL           visible tests fail
  INCONCLUSIVE   a test run produced no parseable result / timed out / no tests
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
TIMEOUT_S = 120


def load_task(task_id: str) -> dict:
    return json.loads((TASKS / task_id / "task.json").read_text())


def _cmd(task: dict, files: list[str]) -> list[str]:
    if task["language"] == "python":
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files]
    return ["node", "--test", "--test-reporter=tap", *files]


def _run(task: dict, cwd: Path, files: list[str]) -> dict:
    try:
        p = subprocess.run(_cmd(task, files), cwd=cwd, capture_output=True, text=True,
                           timeout=TIMEOUT_S, env=_env())
    except subprocess.TimeoutExpired:
        return {"status": "INCONCLUSIVE", "reason": "timeout"}
    out = p.stdout + p.stderr
    if task["language"] == "python":
        m = re.search(r"(\d+) passed", out)
        passed = int(m.group(1)) if m else 0
        failed = re.search(r"(\d+) (failed|error)", out)
    else:
        m = re.search(r"# pass (\d+)", out)
        passed = int(m.group(1)) if m else 0
        f = re.search(r"# fail (\d+)", out)
        failed = f if f and int(f.group(1)) else None
    if p.returncode == 0 and passed > 0 and not failed:
        return {"status": "PASS", "passed": passed}
    if p.returncode == 0:
        return {"status": "INCONCLUSIVE", "reason": "exit 0 but no tests counted"}
    if failed:
        return {"status": "FAIL", "passed": passed}
    return {"status": "INCONCLUSIVE", "reason": f"exit {p.returncode}, unparseable"}


def _env() -> dict:
    import os
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def grade(task_id: str, candidate: dict[str, str] | Path) -> dict:
    """candidate: {relative_path: text} or a directory holding candidate files."""
    task = load_task(task_id)
    tdir = TASKS / task_id
    allowed = set(task["write_paths"])
    if isinstance(candidate, Path):
        files = {str(p.relative_to(candidate)): p.read_text()
                 for p in candidate.rglob("*") if p.is_file()
                 and not {"node_modules", ".git", "__pycache__"} & set(p.parts)}
    else:
        files = dict(candidate)
    ignored = sorted(set(files) - allowed)
    with tempfile.TemporaryDirectory(prefix="abc-grade-") as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(tdir / "repo", work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "node_modules"))
        for rel in sorted(set(files) & allowed):
            (work / rel).write_text(files[rel])
        visible = sorted(str(p.relative_to(work)) for p in work.rglob("*")
                         if p.is_file() and "__pycache__" not in p.parts and re.search(r"(^|/)(test_[^/]*\.py|[^/]*\.test\.js)$",
                                                      str(p.relative_to(work))))
        v = _run(task, work, visible)
        hid_files = []
        for p in (tdir / "hidden").rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = p.relative_to(tdir / "hidden")
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, work / rel)
                hid_files.append(str(rel))
        h = _run(task, work, sorted(hid_files))
    if v["status"] == "INCONCLUSIVE" or h["status"] == "INCONCLUSIVE":
        outcome = "INCONCLUSIVE"
    elif v["status"] == "PASS" and h["status"] == "PASS":
        outcome = "CORRECT"
    elif v["status"] == "PASS":
        outcome = "FALSE_GREEN"
    else:
        outcome = "FAIL"
    return {"task": task_id, "outcome": outcome, "visible": v, "hidden": h,
            "ignored_paths": ignored}


def read_variant(task_id: str, variant: str) -> dict[str, str]:
    d = TASKS / task_id / variant
    return {str(p.relative_to(d)): p.read_text() for p in d.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


if __name__ == "__main__":
    tid, var = sys.argv[1], sys.argv[2]
    cand = {} if var == "repo" else read_variant(tid, var)
    print(json.dumps(grade(tid, cand), indent=2))
