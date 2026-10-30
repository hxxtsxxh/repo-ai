#!/usr/bin/env python3
"""Held-out-6 performance measurements (PROTOCOL.md Amendment 5, "Performance").
Run after `wallclock.py --tag heldout6` for the same project, never next to
another CPU-heavy job.

    VEV_WORK=... python perf6.py [--host] <project> [...]  ->  $VEV_WORK/perf6[-host]-<project>.json

Per project, in the wallclock clone (`$VEV_WORK/wall/new/<project>`, already
initialised and recorded):
- `plan_s`: `verify --json` (no test runs) for each session change, 3 times, median;
- `full_s`: `verify --run --json --full --rerun` for each session change (the
  full-suite mode), with its verdict;
- `fixed`: a change to one test file that adds a comment only:
  `verify --run --json --rerun` 5 times, against the same file run alone in the
  same sandbox 5 times (the per-run fixed cost of verify);
- `noop`: a change to a non-code file only (a new untracked `zz_note.txt`):
  `verify --run --json --rerun` 5 times;
- `startup_s`: the sandbox backend starting an interpreter that does nothing,
  10 times (podman with the project image; with `--host`, the host sandbox).

`--host` measures the same session changes with the host sandbox instead of
the container: a fresh clone, Python dependencies installed into a virtualenv
outside the clone from the corpus test requirements (`VIRTUAL_ENV`), node
dependencies with `npm ci --ignore-scripts` in the clone. It runs the native
suite 3 times, `--record`, then each session change with `verify --run --json`.
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
import scenarios as SC  # noqa: E402
import wallclock as W  # noqa: E402


def med(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 3) if xs else None


def timed(repo: Path, *args: str) -> tuple[float, dict]:
    r = W.ra("new", repo, *args)
    return r["wall_s"], r


def startup(name: str, host: bool) -> list[float]:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor, get_executor
    lang = H.CORPUS[name]["lang"]
    repo = H.WORK / "wall" / "new" / name
    argv = ["python", "-c", "pass"] if lang == "python" else ["node", "-e", "0"]
    out = []
    ws = isolate.materialize(repo, label="perf-startup")
    try:
        ex = (get_executor(repo, "auto", lang) if host else
              Executor(H.backend_for(name), repo, python="python", node="node")).in_workspace(ws)
        for _ in range(10):
            t = time.monotonic()
            ex.run(argv, cwd="", env={}, timeout_s=120, toolchain=lang)
            out.append(round(time.monotonic() - t, 3))
    finally:
        ws.cleanup()
    return out


def single_file(name: str, repo: Path, test: str, host: bool) -> list[float]:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor, get_executor
    runner = H.runner_for(name)
    out = []
    ws = isolate.materialize(repo, label="perf-file")
    try:
        ex = (get_executor(repo, "auto", runner.language) if host else
              Executor(H.backend_for(name), repo, python="python", node="node")).in_workspace(ws)
        for _ in range(5):
            t = time.monotonic()
            ex.run(runner.file_argv(test), cwd=runner.cwd, env=runner.env, timeout_s=600,
                   toolchain="node" if runner.kind == "node" else "python")
            out.append(round(time.monotonic() - t, 3))
    finally:
        ws.cleanup()
    return out


def comment_line(path: str) -> str:
    return "\n# zz perf: comment only\n" if path.endswith(".py") else "\n// zz perf: comment only\n"


def container(name: str) -> dict:
    repo = H.WORK / "wall" / "new" / name
    tc = SC.tc_for(name)
    changes = W._changes(name)
    out: dict = {"project": name, "mode": "container", "plan_s": {}, "full": {}}
    for c in changes:
        H._apply(repo, c)
        try:
            out["plan_s"][c["id"]] = med([timed(repo, "verify", "--json", "--test-command",
                                                H.CORPUS[name]["test_command"])[0] for _ in range(3)])
            wall, r = timed(repo, "verify", "--run", "--json", "--full", "--rerun", *tc)
            out["full"][c["id"]] = {"wall_s": wall, "verdict": ((r.get("data") or {}).get("evidence") or {})
                                    .get("verdict"), "exit": r["exit"], "tree_unchanged": r["tree_unchanged"]}
        finally:
            W._revert(repo)
    t = SC.picks(name)["T"]
    if t:
        with open(repo / t, "a", encoding="utf-8") as fh:
            fh.write(comment_line(t))
        try:
            runs = [timed(repo, "verify", "--run", "--json", "--rerun", *tc) for _ in range(5)]
            out["fixed"] = {"test": t, "verify_s": [w for w, _ in runs],
                            "verdicts": [((r.get("data") or {}).get("evidence") or {}).get("verdict") for _, r in runs],
                            "processes": [(((r.get("data") or {}).get("evidence") or {}).get("processes") or {})
                                          .get("total") for _, r in runs],
                            "file_alone_s": single_file(name, repo, t, host=False)}
        finally:
            W._revert(repo)
    (repo / "zz_note.txt").write_text("perf\n", "utf-8")
    try:
        runs = [timed(repo, "verify", "--run", "--json", "--rerun", *tc) for _ in range(5)]
        out["noop"] = {"verify_s": [w for w, _ in runs],
                       "verdicts": [((r.get("data") or {}).get("evidence") or {}).get("verdict") for _, r in runs]}
    finally:
        W._revert(repo)
    out["startup_s"] = startup(name, host=False)
    return out


def host(name: str) -> dict:
    proj = H.CORPUS[name]
    src = H.WORK / "repos" / name
    repo = H.WORK / "host" / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    out: dict = {"project": name, "mode": "host"}
    if proj["lang"] == "python":
        venv = H.WORK / "hostenv" / name
        if not venv.exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
            subprocess.run([str(venv / "bin" / "pip"), "install", "-q", "--disable-pip-version-check",
                            *proj.get("test_requirements", ["pytest"])], check=True)
        os.environ["VIRTUAL_ENV"] = str(venv)
        out["venv_packages"] = subprocess.run([str(venv / "bin" / "pip"), "freeze"], capture_output=True,
                                              text=True).stdout.split()
    else:
        p = subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=repo,
                           capture_output=True, text=True)
        out["npm_ci_exit"] = p.returncode
        info = repo / ".git" / "info" / "exclude"
        info.write_text(info.read_text("utf-8") + "\nnode_modules/\n", "utf-8")
    W.ra("new", repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    tc = ["--test-command", proj["test_command"]]
    W.NATIVE_RUNS.clear()
    out["native_s"] = W.native(repo, name, [])
    out["native_runs"] = list(W.NATIVE_RUNS)
    rec = W.ra("new", repo, "verify", "--record", "--json", *tc)
    out["record"] = {"wall_s": rec["wall_s"], "exit": rec["exit"], "error": rec.get("error")}
    truth = H.load(name, "truth")
    base = H.load(name, "baseline")
    session = []
    for c in W._changes(name):
        H._apply(repo, c)
        try:
            session.append(W.score("new", c, truth.get(c["id"]) or {}, W.ra("new", repo, "verify", "--run",
                                                                             "--json", *tc), base))
        finally:
            W._revert(repo)
        print(f"  {name} host {c['id']}: {session[-1]['wall_s']}s {session[-1]['verdict']}", flush=True)
    out["session"] = session
    out["startup_s"] = startup_host(repo, name)
    out["summary"] = W.summarize(out)
    return out


def startup_host(repo: Path, name: str) -> list[float]:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import get_executor
    lang = H.CORPUS[name]["lang"]
    argv = ["python", "-c", "pass"] if lang == "python" else ["node", "-e", "0"]
    out = []
    ws = isolate.materialize(repo, label="perf-startup")
    try:
        ex = get_executor(repo, "auto", lang).in_workspace(ws)
        for _ in range(10):
            t = time.monotonic()
            ex.run(argv, cwd="", env={}, timeout_s=120, toolchain=lang)
            out.append(round(time.monotonic() - t, 3))
    finally:
        ws.cleanup()
    return out


def main() -> int:
    args = sys.argv[1:]
    on_host = "--host" in args
    for name in [a for a in args if not a.startswith("--")]:
        print(f"== {name} ({'host' if on_host else 'container'}) at {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
        path = H.WORK / f"perf6{'-host' if on_host else ''}-{name}.json"
        earlier = json.loads(path.read_text("utf-8")) if path.exists() else None
        try:
            res = host(name) if on_host else container(name)
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            res = {"project": name, "error": repr(exc)[:500]}
        if earlier is not None:
            res["_superseded"] = [*(earlier.pop("_superseded", []) or []), earlier]
        path.write_text(json.dumps(res, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
