#!/usr/bin/env python3
"""Developer waiting time and correctness of `repo-ai verify --run`, per
engine, against the project's own full suite, on failing *and* passing
changes.

    VEV_WORK=... python wallclock.py --engine new|old [--tag T] <project> [...]

Engines:
- `new`: the `repo-ai` on PATH (this branch);
- `old`: the previous engine, `$VEV_OLD_ENGINE` (a separate install of an
  earlier commit; see WALLCLOCK.md for the one used).

Per project, in a fresh clone (`$VEV_WORK/wall/<engine>/<project>`) set up as
`e2e.py` does (clean `init`, its files committed):

| step | what |
|---|---|
| `native` | the project's full-suite command, sandboxed, one process, in a disposable copy, x3 (median) |
| `record` | `verify --record` |
| `session` | up to `N_FAIL` failing and `N_PASS` passing changes (by the ground truth), interleaved, each applied, `verify --run --json`, reverted, in one fixed order |
| `repeat` | the last three changes again (the new engine may reuse its evidence), then with `--rerun` (fresh, warm caches) |

Every run is wrapped in a byte-level digest of the clone (everything except
repo-ai's own state directory, which verify writes by design, and git's
object store, which is append-only): `tree_unchanged` compares the two.

Correctness is scored against the ground truth (`truth.json`: the test files
that pass at the base and fail with the change, each run alone in the
network-less container):
- `detected`: a change with affected files whose verdict is `regression`;
- `missed`: a change with affected files whose verdict is not `regression`
  (with the plan's confidence);
- `false_alarm`: a change without affected files whose verdict is `regression`;
- `new_as_preexisting`: a truly affected file reported as already failing at
  the base (the dangerous direction);
- `processes`: sandboxed test processes (the new engine reports them; for the
  old engine they are derived from its evidence: batches + per-file runs +
  base re-checks + full suite, its algorithm being deterministic).

Nothing here changes the frozen held-out protocol (PROTOCOL.md); these are
measurements of the execution engine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402

N_FAIL, N_PASS = 8, 8
OLD = os.environ.get("VEV_OLD_ENGINE", "")
# projects measured in the network-less container even without a project image (peewee: its SQLite
# tests fail under the macOS host sandbox; E2E.md)
PODMAN = set(filter(None, os.environ.get("VEV_WALL_PODMAN", "peewee").split(",")))


def digest(repo: Path) -> str:
    """Every file under the clone except repo-ai's state and git's object store."""
    h = hashlib.sha256()
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith((".repo-ai/state", ".git/objects")) or rel == ".repo-ai/state":
            continue
        try:
            st = path.lstat()
        except OSError:
            continue
        h.update(rel.encode() + b"\0")
        if path.is_symlink():
            h.update(b"L" + os.readlink(path).encode())
        elif path.is_file():
            h.update(b"F%o\0" % (st.st_mode & 0o7777))
            h.update(hashlib.sha256(path.read_bytes()).digest())
        elif path.is_dir():
            h.update(b"D%o" % (st.st_mode & 0o7777))
    return h.hexdigest()[:16]


def ra(engine: str, repo: Path, *args: str) -> dict:
    exe = OLD if engine == "old" else H.RA
    before = digest(repo)
    t = time.monotonic()
    p = subprocess.run([exe, *args], cwd=repo, env=H.env(), capture_output=True, text=True)
    wall = time.monotonic() - t
    after = digest(repo)
    out: dict = {"wall_s": round(wall, 2), "exit": p.returncode, "tree_unchanged": before == after,
                 "t": round(time.time() - wall, 1)}
    if "--json" in args:
        try:
            data = json.loads(p.stdout)
        except ValueError:
            out["error"] = (p.stderr or p.stdout)[-600:]
            return out
        out["data"] = data
    elif p.returncode not in {0, 1}:
        out["error"] = (p.stderr or p.stdout)[-600:]
    return out


def old_processes(ev: dict) -> dict:
    rows = ev.get("results") or []
    m = re.match(r"(\d+) batch", ev.get("execution") or "")
    batches = int(m.group(1)) if m else 0
    per_file = sum(1 for r in rows if not r.get("batched"))
    base = sum(1 for r in rows if r.get("baseline") in {"pass", "fail"})
    full = 1 if (ev.get("full_suite") or {}).get("status") in {"pass", "fail", "timeout"} else 0
    return {"total": batches + per_file + base + full, "batch": batches, "file": per_file, "base": base,
            "full": full, "repeated_file_runs": per_file if batches else 0}


def score(engine: str, change: dict, truth: dict, run: dict, base: dict | None = None) -> dict:
    data = run.get("data") or {}
    ev = data.get("evidence") or {}
    plan = data.get("plan") or {}
    rows = ev.get("results") or []
    affected = set(truth.get("affected") or []) | set(truth.get("timeouts") or [])
    verdict = str(ev.get("verdict", ""))
    new_files = {r["test"] for r in rows if r["status"] not in {"pass", "no-tests"} and
                 (r.get("baseline") in {"pass", "absent"} or r.get("new_failing_tests"))}
    pre_files = {r["test"] for r in rows if r["status"] not in {"pass", "no-tests"} and r["test"] not in new_files
                 and r.get("baseline") == "fail"}
    procs = ev.get("processes") if engine == "new" else old_processes(ev)
    # the ground truth can only judge files that pass at the base in its environment (the container);
    # a file that fails there but passes in the host sandbox is outside what it can say
    judged = {f for f, b in (base or {}).items() if b.get("exit") == 0}
    alarms = sorted((new_files & judged) - affected)
    unjudged = sorted(new_files - judged - affected)
    return {
        "id": change["id"], "kind": change["kind"], "truth_affected": sorted(affected),
        "wall_s": run["wall_s"], "exit": run["exit"], "tree_unchanged": run["tree_unchanged"], "t": run.get("t"),
        "error": run.get("error"), "verdict": verdict, "confidence": plan.get("confidence"),
        "selected": len(plan.get("selected") or []), "universe": plan.get("test_files_total"),
        "strategy": (ev.get("strategy") or {}).get("kind", "targeted" if engine == "old" else None),
        "processes": procs, "reused": bool(ev.get("reused")),
        "base_comparison_s": (ev.get("timing") or {}).get("base_comparison_s"),
        "detected": bool(affected) and verdict == "regression",
        "not_reported_passing": not affected and not str(verdict).startswith(PASSING),
        "missed": bool(affected) and verdict != "regression",
        "false_alarm": verdict == "regression" and bool(alarms) and not affected,
        "false_alarm_files": alarms,
        "regression_outside_ground_truth": verdict == "regression" and not affected and not alarms and bool(unjudged),
        "unjudged_new": unjudged,
        "reported_new": sorted(new_files), "reported_preexisting": sorted(pre_files),
        "new_as_preexisting": sorted(affected & pre_files),
        "affected_not_reported_new": sorted(affected - new_files),
    }


def _changes(name: str) -> list[dict]:
    truth = H.load(name, "truth")
    every = H.load(name, "changes")
    fail = [c for c in every if (truth.get(c["id"]) or {}).get("affected")][:N_FAIL]
    ok = [c for c in every if not (truth.get(c["id"]) or {}).get("affected")
          and not (truth.get(c["id"]) or {}).get("timeouts")][:N_PASS]
    out = []
    for i in range(max(len(fail), len(ok))):  # interleaved: a session mixes both
        out += ([fail[i]] if i < len(fail) else []) + ([ok[i]] if i < len(ok) else [])
    return out


def _revert(repo: Path) -> None:
    H.git(repo, "checkout", "-q", "--", ".")
    subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=repo, check=False)


def native(repo: Path, name: str, sandbox_args: list[str]) -> list[float]:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor, get_executor
    runner = H.runner_for(name)
    out = []
    for _ in range(3):
        ws = isolate.materialize(repo, label="wall-native")
        try:
            if "podman" in sandbox_args:
                ex = Executor(H.backend_for(name), repo, python="python", node="node").in_workspace(ws)
            else:
                ex = get_executor(repo, "auto", runner.language).in_workspace(ws)
            t = time.monotonic()
            res = ex.run(runner.full, cwd=runner.cwd, env=runner.env, timeout_s=3600,
                         toolchain="node" if runner.kind == "node" else "python")
            out.append(round(time.monotonic() - t, 2))
            NATIVE_RUNS.append({"exit": res.exit_code, "timed_out": res.timed_out,
                                "tail": (res.stdout + "\n" + res.stderr)[-400:]})
        finally:
            ws.cleanup()
    return out


NATIVE_RUNS: list[dict] = []  # Amendment 4a: whether the native suite actually ran (exit code, output tail)
PASSING = ("selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected")
VERIFY_STATE = ("evidence", "verify-baseline.json", "verify-timings.json", "verify-scan-cache.json", "gate.json")


def _clear_state(repo: Path) -> None:
    """Amendment 4a cold run: verify's caches and evidence removed (the
    runtime record, `testmap.json`, is kept: it is the user's `--record`)."""
    state = repo / ".repo-ai" / "state"
    for name in VERIFY_STATE:
        path = state / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _files(row: dict) -> dict:
    """What a run concluded per test file: reported new, reported pre-existing."""
    return {"new": row.get("reported_new") or [], "pre": row.get("reported_preexisting") or []}


def measure(engine: str, name: str) -> dict:
    src = H.WORK / "repos" / name
    repo = H.WORK / "wall" / engine / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    proj = H.CORPUS[name]
    sandbox_args = ["--sandbox", "podman"] + (["--image", proj["image"]] if proj.get("image") else []) \
        if proj.get("image") or name in PODMAN else []
    tc = ["--test-command", proj["test_command"], *sandbox_args]
    out: dict = {"project": name, "engine": engine, "test_command": proj["test_command"],
                 "sandbox": "podman" if sandbox_args else "host"}
    out["init"] = {k: v for k, v in ra(engine, repo, "init", "--agent", "none", "-q").items() if k != "data"}
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    NATIVE_RUNS.clear()
    out["native_s"] = native(repo, name, sandbox_args)
    out["native_runs"] = list(NATIVE_RUNS)
    rec = ra(engine, repo, "verify", "--record", "--json", *tc)
    out["record"] = {"wall_s": rec["wall_s"], "exit": rec["exit"], "tree_unchanged": rec["tree_unchanged"],
                     "error": rec.get("error")}
    truth = H.load(name, "truth")
    base = H.load(name, "baseline")
    session = []
    changes = _changes(name)
    for c in changes:
        H._apply(repo, c)
        try:
            run = ra(engine, repo, "verify", "--run", "--json", *tc)
        finally:
            _revert(repo)
        row = score(engine, c, truth.get(c["id"]) or {}, run, base)
        session.append(row)
        print(f"  {name} {engine} {c['id']}: {row['wall_s']}s {row['verdict']} "
              f"procs={(row['processes'] or {}).get('total')}", flush=True)
    out["session"] = session
    repeat = []
    for c in changes[-3:]:
        H._apply(repo, c)
        try:
            again = score(engine, c, truth.get(c["id"]) or {}, ra(engine, repo, "verify", "--run", "--json", *tc), base)
            fresh = score(engine, c, truth.get(c["id"]) or {}, base=base, run=
                          ra(engine, repo, "verify", "--run", "--json", *tc, *(["--rerun"] if engine == "new" else [])))
        finally:
            _revert(repo)
        first = next(s for s in session if s["id"] == c["id"])
        repeat.append({"id": c["id"], "first": first["verdict"], "again": again["verdict"],
                       "again_wall_s": again["wall_s"], "again_reused": again["reused"],
                       "rerun": fresh["verdict"], "rerun_wall_s": fresh["wall_s"],
                       "rerun_processes": (fresh["processes"] or {}).get("total"),
                       "agree": first["verdict"] == again["verdict"] == fresh["verdict"],
                       "tree_unchanged": again["tree_unchanged"] and fresh["tree_unchanged"]})
    out["repeat"] = repeat
    if engine == "new" and os.environ.get("VEV_AMENDMENT_4A") == "1":
        cold = []
        for c in changes[-3:]:
            H._apply(repo, c)
            try:
                _clear_state(repo)
                run = score(engine, c, truth.get(c["id"]) or {}, ra(engine, repo, "verify", "--run", "--json", *tc),
                            base)
            finally:
                _revert(repo)
            first = next(x for x in session if x["id"] == c["id"])
            cold.append({"id": c["id"], "first": first["verdict"], "cold": run["verdict"], "wall_s": run["wall_s"],
                         "files_agree": _files(first) == _files(run), "agree": first["verdict"] == run["verdict"],
                         "tree_unchanged": run["tree_unchanged"]})
        out["cold"] = cold
        serial = []
        for c in changes:  # the selection effect alone: one process at a time (evidence not reused)
            H._apply(repo, c)
            try:
                run = ra(engine, repo, "verify", "--run", "--json", "--rerun", "--workers", "1", *tc)
            finally:
                _revert(repo)
            serial.append(score(engine, c, truth.get(c["id"]) or {}, run, base))
        out["workers1"] = serial
    out["summary"] = summarize(out)
    return out


def summarize(out: dict) -> dict:
    s = out.get("session") or []
    walls = [x["wall_s"] for x in s if not x.get("error")]
    fails = [x for x in s if x["truth_affected"]]
    passes = [x for x in s if not x["truth_affected"]]
    med = (lambda xs: round(statistics.median(xs), 2) if xs else None)
    return {
        "native_median_s": med(out.get("native_s") or []),
        "record_s": (out.get("record") or {}).get("wall_s"),
        "runs": len(s), "errors": sum(1 for x in s if x.get("error")),
        "median_s": med(walls), "median_failing_s": med([x["wall_s"] for x in fails if not x.get("error")]),
        "median_passing_s": med([x["wall_s"] for x in passes if not x.get("error")]),
        "max_s": max(walls) if walls else None, "total_s": round(sum(walls), 2),
        "processes_median": med([float((x["processes"] or {}).get("total") or 0) for x in s]),
        "repeated_file_runs": sum(int((x["processes"] or {}).get("repeated_file_runs") or 0) for x in s),
        "detected": sum(x["detected"] for x in fails), "failing_changes": len(fails),
        "missed": [(x["id"], x["confidence"]) for x in fails if x["missed"]],
        "false_alarms": [x["id"] for x in s if x["false_alarm"]],
        "regressions_outside_ground_truth": [x["id"] for x in s if x["regression_outside_ground_truth"]],
        "new_as_preexisting": sum(len(x["new_as_preexisting"]) for x in s),
        "strategies": {k: sum(1 for x in s if x.get("strategy") == k) for k in {x.get("strategy") for x in s}},
        "tree_unchanged_every_run": all(x["tree_unchanged"] for x in s) and
        all(r["tree_unchanged"] for r in out.get("repeat") or []),
        "repeat_agree": all(r["agree"] for r in out.get("repeat") or []),
        # Amendment 4a
        "not_reported_passing": [x["id"] for x in passes if x.get("not_reported_passing")],
        "native_exits": [r.get("exit") for r in out.get("native_runs") or []],
        "cold_agree": all(r["agree"] and r["files_agree"] for r in out["cold"]) if out.get("cold") else None,
        "median_workers1_s": med([x["wall_s"] for x in out.get("workers1") or [] if not x.get("error")]),
        "workers1_detected": sum(x["detected"] for x in out.get("workers1") or [] if x["truth_affected"]),
        "max_ratio": round(max(walls) / med(out.get("native_s") or []), 2)
        if walls and med(out.get("native_s") or []) else None,
    }


def main() -> int:
    args = sys.argv[1:]
    engine = args[args.index("--engine") + 1] if "--engine" in args else "new"
    tag = args[args.index("--tag") + 1] if "--tag" in args else "dev"
    names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in
                                                                         {"--engine", "--tag"})]
    if engine == "old" and not OLD:
        raise SystemExit("set VEV_OLD_ENGINE to the previous engine's repo-ai executable")
    path = H.WORK / f"wallclock-{tag}-{engine}.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    for n in names:
        print(f"== {n} ({engine}) at {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
        if n in results:  # a re-run never erases an earlier attempt
            results.setdefault("_superseded", []).append(results.pop(n))
        try:
            results[n] = measure(engine, n)
        except Exception as exc:  # noqa: BLE001 - one project's failure is recorded, not hidden
            results[n] = {"project": n, "engine": engine, "error": repr(exc)[:500]}
        print(json.dumps(results[n].get("summary") or results[n].get("error"), indent=1), flush=True)
        path.write_text(json.dumps(results, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
