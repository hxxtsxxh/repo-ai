"""journey-offline-v1 harness (see PREREGISTRATION.md). CI runner only: it clones and tests third-party projects.

    REPO_AI_JOURNEY=1 python benchmarks/journey-offline-v1/run.py --work DIR --out results.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECTS = [
    ("python-humanize/humanize", "4.12.3", ["-e", ".", "pytest", "freezegun"]),
    ("pallets/itsdangerous", "2.2.0", ["-e", ".", "pytest", "freezegun"]),
    ("marshmallow-code/marshmallow", "4.0.0", ["-e", ".", "pytest", "simplejson"]),
]
FIX = re.compile(r"(?i)\bfix(e[sd])?\b")
CONFIG = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "noxfile.py", "conftest.py"}


def sh(cmd, cwd, timeout=1800):
    t = time.perf_counter()
    env = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}
    env["REPO_AI_NO_BACKGROUND"] = "1"
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout + p.stderr, round(time.perf_counter() - t, 3)
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT", round(time.perf_counter() - t, 3)


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout


def is_test(path):
    parts = Path(path).parts
    return path.endswith(".py") and (any(p in {"tests", "test", "testing"} for p in parts[:-1])
                                     or Path(path).name.startswith("test_"))


def select(repo, ref):
    for sha in git(repo, "log", "--no-merges", "--first-parent", "--format=%H", ref, "-n", "600").split():
        subject = git(repo, "log", "-1", "--format=%s", sha)
        if not FIX.search(subject):
            continue
        rows = [r.split("\t") for r in git(repo, "show", "--numstat", "--format=", sha).splitlines() if r.count("\t") == 2]
        if not rows or any(a == "-" for a, _, _ in rows):
            continue
        files = [p for _, _, p in rows]
        lines = sum(int(a) + int(b) for a, b, _ in rows)
        if lines > 300 or {Path(f).name for f in files} & CONFIG or any(Path(f).name.startswith("requirements") for f in files):
            continue
        tests = [f for f in files if is_test(f)]
        src = [f for f in files if f.endswith(".py") and f not in tests]
        if tests and src:
            return sha, subject, tests
    return None


def verify(repo, rai):
    code, out, secs = sh([str(rai), "verify", "--run", "--json"], repo)
    data = {}
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        pass
    summ = data.get("summary") if isinstance(data.get("summary"), dict) else data
    return {"exit": code, "seconds": secs, "verdict": summ.get("verdict"),
            "new_failures": summ.get("new_failures"), "pre_existing": summ.get("pre_existing"),
            "passed_files": summ.get("passed"), "tail": "" if data else out[-800:]}


def native(repo):
    code, out, secs = sh([str(repo / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo)
    return {"exit": code, "seconds": secs, "tail": out[-600:]}


def apply_paths(repo, parent, sha, paths=None):
    diff = git(repo, "diff", parent, sha, *(["--", *paths] if paths else []))
    p = subprocess.run(["git", "apply", "--whitespace=nowarn"], cwd=repo, input=diff, text=True, capture_output=True)
    return p.returncode == 0, p.stderr[-300:]


def reset(repo):
    git(repo, "checkout", "-q", "--", ".")
    git(repo, "clean", "-fdq")


def project(slug, ref, deps, work, rai):
    repo = work / slug.replace("/", "__")
    row = {"project": slug, "ref": ref}
    code, out, _ = sh(["git", "clone", "-q", f"https://github.com/{slug}.git", str(repo)], work)
    if code:
        return {**row, "status": "CLONE_FAILED", "detail": out[-300:]}
    git(repo, "checkout", "-q", "--detach", ref)
    picked = select(repo, ref)
    if not picked:
        return {**row, "status": "NO_FIX_COMMIT"}
    sha, subject, tests = picked
    parent = git(repo, "rev-parse", f"{sha}^").strip()
    git(repo, "checkout", "-q", "--detach", parent)
    row.update({"fix_commit": sha, "subject": subject, "test_files": tests, "parent": parent})
    sh([sys.executable, "-m", "venv", ".venv"], repo)
    code, out, _ = sh([str(repo / ".venv/bin/python"), "-m", "pip", "install", "-q", *deps], repo)
    if code:
        return {**row, "status": "INSTALL_FAILED", "detail": out[-600:]}
    with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("\n.venv/\n")
    steps = {}
    for name, cmd in (("quickstart", ["quickstart"]), ("init", ["init", "--agent", "none"]),
                      ("record", ["verify", "--record"])):
        c, o, s = sh([str(rai), *cmd], repo)
        steps[name] = {"exit": c, "seconds": s, "tail": o[-400:]}
    git(repo, "add", "-A")  # init's own files: committed, as a user would
    git(repo, "-c", "user.email=j@example.invalid", "-c", "user.name=journey", "commit", "-qm", "repo-ai init", "--allow-empty")
    base = git(repo, "rev-parse", "HEAD").strip()
    for label, paths in (("fix", None), ("test_without_fix", tests)):
        ok, err = apply_paths(repo, parent, sha, paths)
        if not ok:
            steps[label] = {"status": "APPLY_FAILED", "detail": err}
            reset(repo)
            continue
        steps[label] = {"native": native(repo), "verify": verify(repo, rai)}
        reset(repo)
    c, o, s = sh([str(rai), "privacy", "audit"], repo)
    steps["privacy_audit"] = {"exit": c, "tail": o[-400:]}
    c, o, s = sh([str(rai), "uninstall", "--agent", "all", "--yes"], repo)
    steps["uninstall"] = {"exit": c, "tail": o[-300:], "porcelain": git(repo, "status", "--porcelain")[:400],
                          "base": base}
    return {**row, "status": "RAN", "steps": steps}


def gates(rows):
    j1, j2, j3 = [], [], []
    for r in rows:
        st = r.get("steps") or {}
        t = st.get("test_without_fix") or {}
        if t.get("verify", {}).get("exit") == 0 and t.get("native", {}).get("exit") not in (0, None):
            j1.append(r["project"])
        f = st.get("fix") or {}
        if f.get("native", {}).get("exit") == 0:
            j2.append((r["project"], f.get("verify", {}).get("exit") == 0))
        if "uninstall" in st:
            j3.append((r["project"], st["uninstall"]["porcelain"] == ""))
    return {"J1_false_assurance": {"cases": j1, "pass": not j1},
            "J2_fix_passes_where_native_passes": j2, "J3_uninstall_clean": j3}


def main():
    if os.environ.get("REPO_AI_JOURNEY") != "1":
        print("journey-offline-v1 clones and tests third-party projects: CI only (REPO_AI_JOURNEY=1)", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    rai = Path(sys.executable).parent / "repo-ai"
    rows = []
    for slug, ref, deps in PROJECTS:
        try:
            rows.append(project(slug, ref, deps, work, rai))
        except Exception as exc:
            rows.append({"project": slug, "status": "HARNESS_ERROR", "detail": repr(exc)[:400]})
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip()
    res = {"protocol": "journey-offline-v1", "commit": head, "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gates": gates(rows), "projects": rows}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res["gates"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
