"""journey-offline-v2 harness (see PREREGISTRATION.md). CI runner only: it clones and tests third-party projects.

    REPO_AI_JOURNEY=1 python benchmarks/journey-offline-v2/run.py --work DIR --out results.json
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
    ("jpadilla/pyjwt", "2.10.1", ["-e", ".[crypto]", "pytest"]),
    ("python-humanize/humanize", "4.12.3", ["-e", ".", "pytest", "freezegun"]),
    ("more-itertools/more-itertools", "v10.7.0", ["-e", ".", "pytest"]),
    ("pallets/itsdangerous", "2.2.0", ["-e", ".", "pytest", "freezegun"]),
    ("marshmallow-code/marshmallow", "4.0.0", ["-e", ".", "pytest", "simplejson"]),
]
FIX = re.compile(r"(?i)\bfix(e[sd])?\b|\bbug\b|\bregression\b")
CONFIG = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "noxfile.py", "conftest.py"}
DEFECTS, TRIES, SCAN, MAX_LINES = 2, 15, 200, 400


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


def candidates(repo, ref):
    for sha in git(repo, "log", "--first-parent", "--format=%H", ref, "-n", str(SCAN)).split():
        parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
        if not parents:
            continue
        base = parents[0]  # a merge counts as its pull request's whole change
        if not FIX.search(git(repo, "log", "-1", "--format=%B", sha)):
            continue
        rows = [r.split("\t") for r in git(repo, "diff", "--numstat", base, sha).splitlines() if r.count("\t") == 2]
        if not rows or any(a == "-" for a, _, _ in rows):
            continue
        files = [p for _, _, p in rows]
        if sum(int(a) + int(b) for a, b, _ in rows) > MAX_LINES or {Path(f).name for f in files} & CONFIG \
                or any(Path(f).name.startswith("requirements") for f in files):
            continue
        tests = [f for f in files if is_test(f)]
        if tests and any(f.endswith(".py") and f not in tests for f in files):
            yield sha, base, tests


def native(repo):
    code, out, secs = sh([str(repo / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo)
    return {"exit": code, "seconds": secs, "tail": out[-500:]}


def apply(repo, base, head, paths=None):
    diff = git(repo, "diff", base, head, *(["--", *paths] if paths else []))
    p = subprocess.run(["git", "apply", "--whitespace=nowarn"], cwd=repo, input=diff, text=True, capture_output=True)
    return p.returncode == 0


def reset(repo):
    git(repo, "checkout", "-q", "-f", "--", ".")
    git(repo, "clean", "-fdq")


def verify(repo, rai):
    code, out, secs = sh([str(rai), "verify", "--run", "--json"], repo)
    data = {}
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        pass
    s = data.get("summary") if isinstance(data.get("summary"), dict) else data
    return {"exit": code, "seconds": secs, "verdict": s.get("verdict"), "new_failures": s.get("new_failures"),
            "pre_existing": s.get("pre_existing"), "passed_files": s.get("passed"), "tail": "" if data else out[-800:]}


def journey(repo, rai, sha, base, tests):
    git(repo, "checkout", "-q", "-f", "--detach", base)
    git(repo, "clean", "-fdq")
    steps = {}
    for name, cmd in (("quickstart", ["quickstart"]), ("init", ["init", "--agent", "none"]),
                      ("record", ["verify", "--record"])):
        c, o, s = sh([str(rai), *cmd], repo)
        steps[name] = {"exit": c, "seconds": s, "tail": o[-300:]}
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=j@example.invalid", "-c", "user.name=journey", "commit", "-qm", "repo-ai init",
        "--allow-empty")
    for label, paths in (("test_without_fix", tests), ("fix", None)):
        if not apply(repo, base, sha, paths):
            steps[label] = {"status": "APPLY_FAILED"}
        else:
            steps[label] = {"native": native(repo), "verify": verify(repo, rai)}
        reset(repo)
    c, o, _ = sh([str(rai), "uninstall", "--agent", "all", "--yes"], repo)
    steps["uninstall"] = {"exit": c, "tail": o[-300:], "tracked_diff_from_base": git(repo, "diff", "--stat", base),
                          "untracked": git(repo, "ls-files", "--others", "--exclude-standard")}
    return steps


def project(slug, ref, deps, work, rai):
    repo = work / slug.replace("/", "__")
    row = {"project": slug, "ref": ref, "defects": [], "rejected": []}
    code, out, _ = sh(["git", "clone", "-q", f"https://github.com/{slug}.git", str(repo)], work)
    if code:
        return {**row, "status": "CLONE_FAILED", "detail": out[-300:]}
    git(repo, "checkout", "-q", "--detach", ref)
    sh([sys.executable, "-m", "venv", ".venv"], repo)
    code, out, _ = sh([str(repo / ".venv/bin/python"), "-m", "pip", "install", "-q", *deps], repo)
    if code:
        return {**row, "status": "INSTALL_FAILED", "detail": out[-600:]}
    with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("\n.venv/\n")
    tried = 0
    for sha, base, tests in candidates(repo, ref):
        if len(row["defects"]) >= DEFECTS or tried >= TRIES:
            break
        tried += 1
        git(repo, "checkout", "-q", "-f", "--detach", base)
        git(repo, "clean", "-fdq")
        base_native = native(repo)
        if base_native["exit"] != 0:
            row["rejected"].append({"commit": sha, "why": "base suite does not pass", "exit": base_native["exit"]})
            continue
        if not apply(repo, base, sha, tests):
            row["rejected"].append({"commit": sha, "why": "test changes do not apply alone"})
            reset(repo)
            continue
        without = native(repo)
        reset(repo)
        if without["exit"] == 0:
            row["rejected"].append({"commit": sha, "why": "tests pass without the fix"})
            continue
        subject = git(repo, "log", "-1", "--format=%s", sha).strip()
        row["defects"].append({"commit": sha, "base": base, "subject": subject, "test_files": tests,
                               "steps": journey(repo, rai, sha, base, tests)})
    row["tried"] = tried
    row["status"] = "RAN"
    return row


def gates(rows):
    j1, j2, j3 = [], [], []
    for r in rows:
        for d in r.get("defects", []):
            st = d["steps"]
            t, f = st.get("test_without_fix") or {}, st.get("fix") or {}
            if t.get("verify", {}).get("exit") == 0:
                j1.append(f"{r['project']}@{d['commit'][:8]}")
            if f.get("native", {}).get("exit") == 0:
                j2.append([f"{r['project']}@{d['commit'][:8]}", f.get("verify", {}).get("exit") == 0])
            u = st.get("uninstall", {})
            j3.append([f"{r['project']}@{d['commit'][:8]}", not u.get("tracked_diff_from_base") and not u.get("untracked")])
    n = sum(len(r.get("defects", [])) for r in rows)
    return {"defects": n, "J1_false_assurance": {"cases": j1, "pass": not j1},
            "J2_fix_passes_where_native_passes": j2, "J3_uninstall_restores_base": j3}


def main():
    if os.environ.get("REPO_AI_JOURNEY") != "1":
        print("journey-offline-v2 clones and tests third-party projects: CI only (REPO_AI_JOURNEY=1)", file=sys.stderr)
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
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True,
                          text=True).stdout.strip()
    res = {"protocol": "journey-offline-v2", "commit": head, "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gates": gates(rows), "projects": rows}
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(res["gates"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
