"""speed-v1 harness (see PREREGISTRATION.md). Runs on a disposable CI runner, never on a developer machine:
it clones third-party projects and runs their test suites.

    REPO_AI_SPEED_BENCH=1 python benchmarks/speed-v1/run.py --work DIR --out results.json
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECTS = [  # (slug, ref, pip install arguments) — fixed by the preregistration
    ("jpadilla/pyjwt", "2.10.1", ["-e", ".[crypto]", "pytest"]),
    ("python-humanize/humanize", "4.12.3", ["-e", ".", "pytest", "freezegun"]),
    ("more-itertools/more-itertools", "v10.7.0", ["-e", ".", "pytest"]),
    ("pallets/itsdangerous", "2.2.0", ["-e", ".", "pytest", "freezegun"]),
    ("marshmallow-code/marshmallow", "4.0.0", ["-e", ".", "pytest", "simplejson"]),
]
CHANGES_PER_PROJECT = 6
MAX_LINES = 300
CONFIG_FILES = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "noxfile.py", "conftest.py"}
TEST_DIRS = {"tests", "test", "testing"}


def sh(cmd: list[str], cwd: Path, timeout: int = 1800, env: dict[str, str] | None = None) -> tuple[int, str, float]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        out, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = f"TIMEOUT after {timeout}s: {exc}", 124
    return code, out, time.perf_counter() - start


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def eligible(repo: Path, sha: str) -> bool:
    stat = git(repo, "show", "--numstat", "--format=", sha).splitlines()
    files, lines = [], 0
    for row in stat:
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        if added == "-":  # binary
            return False
        files.append(path)
        lines += int(added) + int(removed)
    if not files or lines > MAX_LINES:
        return False
    names = {Path(f).name for f in files}
    if names & CONFIG_FILES or any(Path(f).name.startswith("requirements") for f in files):
        return False
    return any(f.endswith(".py") and not (set(Path(f).parts[:-1]) & TEST_DIRS)
               and not Path(f).name.startswith("test_") for f in files)


def select_changes(repo: Path, ref: str) -> list[str]:
    out = []
    for sha in git(repo, "log", "--no-merges", "--first-parent", "--format=%H", ref, "-n", "400").split():
        if len(out) == CHANGES_PER_PROJECT:
            break
        if eligible(repo, sha):
            out.append(sha)
    return out


def verify(repo: Path, rai: Path, *extra: str) -> dict:
    env = {**os.environ, "REPO_AI_NO_BACKGROUND": "1"}
    code, out, secs = sh([str(rai), "verify", "--run", "--json", *extra], repo, env=env)
    data: dict = {}
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else {}
    except json.JSONDecodeError:
        data = {}
    def field(name: str):  # the report's fields may sit at the top level or under "summary"
        return data.get(name, (data.get("summary") or {}).get(name) if isinstance(data.get("summary"), dict) else None)
    return {"seconds": round(secs, 3), "exit": code, "verdict": field("verdict"), "strategy": field("strategy"),
            "reused": field("reused"), "passed_files": field("passed"), "processes": field("processes"),
            "new_failures": len(field("new_failures") or []), "tail": "" if data else out[-600:],
            # what failed, so a disagreement with the native suite can be explained (run 1 could not)
            "detail": {k: field(k) for k in ("new_failures", "pre_existing", "failing_differently", "unconfirmed",
                                             "not_compared", "no_tests", "not_run", "full_suite_counts")}}


def native(repo: Path) -> dict:
    py = str(repo / ".venv" / "bin" / "python")
    runs = [sh([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo) for _ in range(3)]
    secs = [r[2] for r in runs]
    return {"seconds": [round(s, 3) for s in secs], "median": round(statistics.median(secs), 3),
            "exit": [r[0] for r in runs], "tail": runs[-1][1][-1500:]}


def project(slug: str, ref: str, deps: list[str], work: Path, rai: Path) -> dict:
    repo = work / slug.replace("/", "__")
    row: dict = {"project": slug, "ref": ref, "changes": []}
    code, out, _ = sh(["git", "clone", "-q", f"https://github.com/{slug}.git", str(repo)], work)
    if code:
        return {**row, "status": "CLONE_FAILED", "detail": out[-300:]}
    git(repo, "checkout", "-q", "--detach", ref)
    sh([sys.executable, "-m", "venv", ".venv"], repo)
    code, out, _ = sh([str(repo / ".venv" / "bin" / "python"), "-m", "pip", "install", "-q", *deps], repo)
    if code:
        return {**row, "status": "INSTALL_FAILED", "detail": out[-600:]}
    base = native(repo)
    row["baseline"] = base
    if any(base["exit"]):
        return {**row, "status": "INVALID_BASELINE"}
    sh([str(rai), "init", "--agent", "none", "-q"], repo)
    git(repo, "checkout", "-q", "--", ".")  # keep only the replayed change in the working tree
    with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("\n.repo-ai/\n.venv/\n")
    for sha in select_changes(repo, ref):
        parent = git(repo, "rev-parse", f"{sha}^").strip()
        git(repo, "checkout", "-q", "--detach", parent)
        diff = git(repo, "diff", parent, sha)
        applied = subprocess.run(["git", "apply", "--whitespace=nowarn"], cwd=repo, input=diff, text=True,
                                 capture_output=True)
        change: dict = {"commit": sha, "parent": parent}
        if applied.returncode:
            change["status"] = "APPLY_FAILED"
            row["changes"].append(change)
            continue
        change["native"] = native(repo)
        change["verify_cold"] = verify(repo, rai)
        change["verify_reuse"] = verify(repo, rai)
        change["verify_rerun"] = verify(repo, rai, "--rerun")
        med = change["native"]["median"]
        change["ratio_cold"] = round(change["verify_cold"]["seconds"] / med, 3) if med else None
        change["status"] = "MEASURED"
        row["changes"].append(change)
        git(repo, "checkout", "-q", "--", ".")
        git(repo, "clean", "-fdq")  # files the commit added (Amendment 2); ignored .venv and .repo-ai/ stay
    row["status"] = "MEASURED"
    return row


def summary(projects: list[dict]) -> dict:
    ratios = [c["ratio_cold"] for p in projects for c in p.get("changes", [])
              if c.get("status") == "MEASURED" and c.get("ratio_cold")]
    per = {p["project"]: statistics.median([c["ratio_cold"] for c in p["changes"]
                                           if c.get("status") == "MEASURED" and c.get("ratio_cold")] or [0])
           for p in projects if p.get("status") == "MEASURED"}
    geo = round(statistics.geometric_mean(ratios), 3) if ratios else None
    slower = sum(1 for r in ratios if r > 1.0)
    faster_claim = bool(ratios) and geo is not None and geo < 1.0 and slower < len(ratios) / 2
    return {"valid_changes": len(ratios), "geometric_mean_cold_ratio": geo, "slower_than_native": slower,
            "per_project_median_cold_ratio": per, "reading_rule_faster": faster_claim}


def main() -> int:
    if os.environ.get("REPO_AI_SPEED_BENCH") != "1":
        print("speed-v1 clones third-party projects and runs their suites: CI only (REPO_AI_SPEED_BENCH=1)",
              file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    rai = Path(sys.executable).parent / "repo-ai"
    rows = []
    for slug, ref, deps in PROJECTS:
        try:
            rows.append(project(slug, ref, deps, work, rai))
        except Exception as exc:  # recorded, never hidden
            rows.append({"project": slug, "ref": ref, "status": "HARNESS_ERROR", "detail": repr(exc)[:400]})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "changes"})[:400], flush=True)
    cpu = ""
    try:
        cpu = next(line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name"))
    except (OSError, StopIteration):
        pass
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, capture_output=True,
                          text=True).stdout.strip()
    result = {"protocol": "speed-v1", "commit": head, "python": platform.python_version(),
              "os": platform.platform(), "cpus": os.cpu_count(), "cpu_model": cpu,
              "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "summary": summary(rows),
              "projects": rows}
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
