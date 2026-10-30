#!/usr/bin/env python3
"""Actual verification time and working-tree safety (PROTOCOL.md Amendment 2).

The product path, as a developer would run it:
- `repo-ai verify --record` once;
- then `repo-ai verify --run` for each sampled change;
- all in the project's network-less container image (`--sandbox podman
  --image ...`), through the engine's disposable copies.

The comparison is the project's full suite in the same container.

Sample: the first 10 detected and the first 5 undetected changes, in change
order.

**Safety:**
- every invocation's `source_tree.unchanged`;
- a byte-for-byte digest of the clone (`.git` and ignored files included,
  repo-ai's own state excluded) before and after the whole run.

    VEV_WORK=... python actual.py <project> [...]
"""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

ACT = H.WORK / "actual"


def digest(root: Path, skip_index: bool = False) -> str:
    """Every path under the clone, `.git` and ignored files included (repo-ai's own
    state excluded). `skip_index`: also leave out `.git/index`, which the harness's
    own `git checkout` between changes rewrites (a stat cache)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel == ".repo-ai/state" or rel.startswith(".repo-ai/state/") or (skip_index and rel == ".git/index"):
            continue
        h.update(rel.encode())
        if p.is_symlink():
            h.update(b"L" + str(p.readlink()).encode())
        elif p.is_file():
            h.update(b"F" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def ra(repo: Path, *args: str) -> dict:
    t = time.monotonic()
    p = subprocess.run([H.RA, *args], cwd=repo, env=H.env(), capture_output=True, text=True)
    out: dict = {"wall_s": round(time.monotonic() - t, 2), "exit": p.returncode}
    try:
        data = json.loads(p.stdout)
    except ValueError:
        out["error"] = (p.stderr or p.stdout)[-400:]
        return out
    ev = data.get("evidence") or {}
    plan = data.get("plan") or data
    out.update({"selected": len(plan.get("selected") or []), "universe": plan.get("test_files_total"),
                "confidence": plan.get("confidence"), "verdict": ev.get("verdict"),
                "unchanged": (ev.get("source_tree") or {}).get("unchanged"),
                "full_suite_ran": bool(ev.get("full_suite") and ev["full_suite"].get("status") in
                                       {"pass", "fail", "timeout"})})
    return out


def full_suite(repo: Path, name: str) -> dict:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor
    runner = H.runner_for(name)
    ws = isolate.materialize(repo, label="actual-full")
    try:
        ex = Executor(H.backend_for(name), repo, python="python", node="node", timeout_s=3600).in_workspace(ws)
        t = time.monotonic()
        res = ex.run(runner.full, cwd=runner.cwd, env=runner.env, timeout_s=3600,
                     toolchain="node" if runner.kind == "node" else "python")
        return {"wall_s": round(time.monotonic() - t, 2), "exit": res.exit_code}
    finally:
        ws.cleanup()


def measure(name: str) -> dict:
    src = H.WORK / "repos" / name
    repo = ACT / name
    if repo.exists():
        shutil.rmtree(repo)
    ACT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    # the same environment rule as ground truth, committed so it is part of the base, not of each change
    H._install_metadata(repo)
    image = H.CORPUS[name].get("image") or H.sandbox.DEFAULT_IMAGES[H.CORPUS[name]["lang"]]
    box = ["--sandbox", "podman", "--image", image, "--test-command", H.CORPUS[name]["test_command"]]
    out: dict = {"project": name, "image": image}
    subprocess.run([H.RA, "init", "--agent", "none", "-q"], cwd=repo, env=H.env(), check=True,
                   capture_output=True)
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "eval environment", check=False)
    before = digest(repo, skip_index=True)
    out["full_suite"] = [full_suite(repo, name) for _ in range(2)]
    out["record"] = ra(repo, "verify", "--record", "--json", *box)
    truth = H.load(name, "truth")
    changes = H.load(name, "changes")
    detected = [c for c in changes if truth.get(c["id"], {}).get("affected")][:10]
    undetected = [c for c in changes if not truth.get(c["id"], {}).get("affected")][:5]
    runs = []
    for c in detected + undetected:
        H._apply(repo, c)
        try:
            pre = digest(repo)          # the working tree with the change, exactly as the developer has it
            r = ra(repo, "verify", "--run", "--json", *box)
            r["byte_identical_around_run"] = digest(repo) == pre   # independent of verify's own check
        finally:
            H.git(repo, "checkout", "-q", "--", ".")
            subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=repo, check=False)
        runs.append({"id": c["id"], "detected": c in detected, **r})
    out["runs"] = runs
    after = digest(repo, skip_index=True)
    t_full = statistics.median(f["wall_s"] for f in out["full_suite"])
    walls = [r["wall_s"] for r in runs if "error" not in r]
    out["summary"] = {
        "full_suite_s": t_full, "record_s": out["record"]["wall_s"],
        "verify_run_median_s": round(statistics.median(walls), 2) if walls else None,
        "verify_run_mean_s": round(statistics.mean(walls), 2) if walls else None,
        "median_share_of_full_suite_wall": round(statistics.median(walls) / t_full, 3) if walls and t_full else None,
        "runs": len(runs), "errors": sum(1 for r in runs if "error" in r),
        "every_run_reported_tree_unchanged": all(r.get("unchanged") is True for r in runs),
        "every_run_byte_identical_by_independent_digest": all(r.get("byte_identical_around_run") for r in runs),
        "clone_identical_before_and_after_except_git_index": before == after,
    }
    return out


def main() -> int:
    path = H.WORK / "actual-results.json"
    results = json.loads(path.read_text("utf-8")) if path.exists() else {}
    for n in sys.argv[1:]:
        print(f"== {n}", flush=True)
        results[n] = measure(n)
        print(json.dumps(results[n]["summary"], indent=1), flush=True)
        path.write_text(json.dumps(results, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
