#!/usr/bin/env python3
"""End-to-end wall-clock cost of using `repo-ai verify`, against running the
project's own full suite in the same sandbox.

Everything is measured as a developer would experience it: the wall time of
the whole `repo-ai` command (planning, the disposable copy, sandbox start-up,
the selected tests, base-revision re-checks, evidence), not the sum of
per-file test times. Every test run is sandboxed; nothing runs on the host
unsandboxed.

Per project, in a fresh clone (`$VEV_WORK/e2e/<project>`):

| step | what |
|---|---|
| `init` | clean first-time `repo-ai init --agent none` |
| `full_suite` | the project's full-suite command, sandboxed, in a disposable copy (x2) |
| `record` | `verify --record` (one run of every test file under the tracer) |
| `single` | one detected change: `verify` (plan) and `verify --run` |
| `same_file` | three successive edits to one file, `verify --run` after each |
| `broad` | five detected changes in five files at once, `verify --run` |
| `config` | the change plus a dependency/config edit: `verify --run` (full suite required) |
| `stale` | change committed, a second change on top: plan and `--run` with stale evidence, then re-record |
| `full` | `verify --run --full` |
| `session` | ten changes in a row (apply, `verify --run`, revert) |

    VEV_WORK=... python e2e.py <project> [...]
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

E2E = H.WORK / "e2e"
# host (default: seatbelt/bwrap with the project's interpreter) or podman (the ground-truth image)
SANDBOX = os.environ.get("VEV_E2E_SANDBOX", "auto")


def ra(repo: Path, *args: str) -> dict:
    """One repo-ai command: wall time, max RSS of the repo-ai process, exit."""
    t = time.monotonic()
    p = subprocess.run(["/usr/bin/time", "-l", H.RA, *args], cwd=repo, env=H.env(), capture_output=True,
                       text=True)
    wall = time.monotonic() - t
    rss = 0
    own: list[str] = []
    for line in p.stderr.splitlines():
        if "maximum resident set size" in line:
            try:
                rss = int(line.split()[0])
            except ValueError:
                pass
        if not line.startswith(" ") and not line.strip().endswith(("real", "user", "sys")):
            own.append(line)  # repo-ai's own stderr, without /usr/bin/time's statistics
    out: dict = {"wall_s": round(wall, 2), "exit": p.returncode, "max_rss_mb": round(rss / 1e6, 1)}
    if "--json" in args:
        try:
            data = json.loads(p.stdout)
            plan = data.get("plan", data)
            ev = data.get("evidence") or {}
            out.update({"selected": len(plan.get("selected", [])), "universe": plan.get("test_files_total"),
                        "confidence": plan.get("confidence"), "verdict": ev.get("verdict"),
                        "full_suite_ran": bool(ev.get("full_suite") and ev["full_suite"].get("status") in
                                               {"pass", "fail", "timeout"}),
                        "test_seconds": round(sum(r.get("duration_s", 0) for r in ev.get("results", [])), 2),
                        "isolation_s": (ev.get("isolation") or {}).get("seconds"),
                        "integrity_s": (ev.get("source_tree") or {}).get("check_seconds"),
                        "unchanged": (ev.get("source_tree") or {}).get("unchanged")})
        except ValueError:
            out["error"] = ("\n".join(own) or p.stdout)[-500:]
    if p.returncode not in {0, 1} and "error" not in out:
        out["error"] = "\n".join(own)[-500:]
    return out


def full_suite(repo: Path, name: str) -> dict:
    """The project's full-suite command, sandboxed (seatbelt/bwrap, the
    project's interpreter) in a disposable copy: the native comparison."""
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    runner = H.runner_for(name)
    ws = isolate.materialize(repo, label="e2e-full")
    try:
        if SANDBOX == "podman":
            from repo_ai.verify.execute import Executor
            ex = Executor(H.backend_for(name), repo, python="python", node="node").in_workspace(ws)
        else:
            ex = get_executor(repo, SANDBOX, runner.language).in_workspace(ws)
        t = time.monotonic()
        res = ex.run(runner.full, cwd=runner.cwd, env=runner.env, timeout_s=3600,
                     toolchain="node" if runner.kind == "node" else "python")
        return {"wall_s": round(time.monotonic() - t, 2), "exit": res.exit_code, "backend": res.backend}
    finally:
        ws.cleanup()


def _changes(name: str) -> list[dict]:
    truth = H.load(name, "truth")
    return [c for c in H.load(name, "changes") if truth.get(c["id"], {}).get("affected")]


def _revert(repo: Path) -> None:
    H.git(repo, "checkout", "-q", "--", ".")
    subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=repo, check=False)


def measure(name: str) -> dict:
    src = H.WORK / "repos" / name
    repo = E2E / name
    if repo.exists():
        shutil.rmtree(repo)
    E2E.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)  # the ground-truth environment rule, committed with init below
    cmd = H.CORPUS[name]["test_command"]
    tc = ["--test-command", cmd] + (["--sandbox", SANDBOX] if SANDBOX != "auto" else [])
    detected = _changes(name)
    out: dict = {"project": name, "test_command": cmd, "detected_changes_available": len(detected),
                 "sandbox": SANDBOX}
    out["init"] = ra(repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")  # init's own files, so they are not part of every change
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    out["full_suite"] = [full_suite(repo, name) for _ in range(2)]
    t_full = statistics.median(r["wall_s"] for r in out["full_suite"])
    out["record"] = ra(repo, "verify", "--record", "--json", *tc)

    def run_change(changes: list[dict], extra: tuple[str, ...] = ()) -> dict:
        for c in changes:
            H._apply(repo, c)
        try:
            return {"plan": ra(repo, "verify", "--json", *tc), "run": ra(repo, "verify", "--run", "--json", *tc, *extra)}
        finally:
            _revert(repo)

    if not detected:
        return out
    out["single"] = run_change(detected[:1])
    # three successive edits to the same file (cumulative)
    first_file = next(iter(detected[0]["files"]))
    same = [c for c in H.load(name, "changes") if list(c["files"]) == [first_file] and c["kind"] == "mutation"][:3]
    seq = []
    try:
        for c in same:
            H._apply(repo, c)  # each replaces the file's content: three successive edits
            seq.append(ra(repo, "verify", "--run", "--json", *tc))
    finally:
        _revert(repo)
    out["same_file"] = seq
    # five detected changes in five distinct files
    picked, seen = [], set()
    for c in detected:
        files = set(c["files"])
        if not files & seen:
            picked.append(c)
            seen |= files
        if len(picked) == 5:
            break
    out["broad"] = {"files": len(seen), **run_change(picked)}
    # a dependency/config edit on top of a change
    cfg = next((p for p in ("pyproject.toml", "setup.cfg", "package.json", "tox.ini") if (repo / p).exists()), "")
    if cfg:
        H._apply(repo, detected[0])
        text = (repo / cfg).read_text("utf-8")
        if cfg == "package.json":
            data = json.loads(text)
            data["version"] = str(data.get("version", "0.0.0")) + "-e2e"
            (repo / cfg).write_text(json.dumps(data, indent=2) + "\n", "utf-8")
        else:
            (repo / cfg).write_text(text + "\n# e2e: a configuration edit\n", "utf-8")
        try:
            out["config"] = {"file": cfg, "plan": ra(repo, "verify", "--json", *tc),
                             "run": ra(repo, "verify", "--run", "--json", *tc)}
        finally:
            _revert(repo)
    # stale evidence: commit one change, then make another
    if len(detected) > 1:
        H._apply(repo, detected[0])
        H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qam", "e2e: committed change")
        H._apply(repo, detected[1])
        try:
            out["stale"] = {"plan": ra(repo, "verify", "--json", *tc), "run": ra(repo, "verify", "--run", "--json", *tc)}
        finally:
            _revert(repo)
        out["stale"]["re_record"] = ra(repo, "verify", "--record", "--json", *tc)
        H.git(repo, "reset", "-q", "--hard", "HEAD~1")
        out["record_after_reset"] = ra(repo, "verify", "--record", "--json", *tc)
    out["full"] = run_change(detected[:1], ("--full",))
    # a session of ten changes
    session = []
    for c in detected[:10]:
        r = run_change([c])
        session.append({"id": c["id"], "plan_s": r["plan"]["wall_s"], "run_s": r["run"]["wall_s"],
                        "selected": r["run"].get("selected"), "verdict": r["run"].get("verdict"),
                        "full_suite_ran": r["run"].get("full_suite_ran"), "unchanged": r["run"].get("unchanged"),
                        "exit": r["run"].get("exit"), "error": r["run"].get("error")})
    out["session"] = session
    runs = [s["run_s"] for s in session]
    saved = t_full - statistics.mean(runs) if runs else 0.0
    out["summary"] = {
        "full_suite_s": t_full, "record_s": out["record"]["wall_s"], "init_s": out["init"]["wall_s"],
        "verify_run_median_s": round(statistics.median(runs), 2) if runs else None,
        "verify_run_mean_s": round(statistics.mean(runs), 2) if runs else None,
        "session_total_s": round(sum(runs), 2), "full_suite_x_session_s": round(t_full * len(runs), 2),
        "saved_per_change_s": round(saved, 2),
        "break_even_changes": (round((out["record"]["wall_s"] + out["init"]["wall_s"]) / saved, 1)
                               if saved > 0 else None),
        # integrity is reported by every run that produced evidence; errors are counted apart
        "runs_with_evidence": sum(1 for s in session if s["unchanged"] is not None),
        "runs_with_errors": sum(1 for s in session if s["unchanged"] is None),
        "tree_unchanged_every_run": all(s["unchanged"] is True for s in session if s["unchanged"] is not None),
    }
    return out


def main() -> int:
    names = sys.argv[1:]
    results = {}
    for n in names:
        print(f"== {n}", flush=True)
        r = measure(n)
        results[n] = r
        print(json.dumps(r.get("summary", {}), indent=1), flush=True)
        (H.WORK / "e2e-results.json").write_text(json.dumps(results, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
