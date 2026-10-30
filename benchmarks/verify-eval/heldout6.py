#!/usr/bin/env python3
"""Held-out-6 driver (PROTOCOL.md Amendment 5): the steps in their fixed
order for one project at a time. The steps never run concurrently.

    VEV_WORK=... python heldout6.py <step> <project> [...]

Steps:
- `truth`: image, setup, baseline, record, changes, truth and selection (`harness.py`);
- `wall`: `wallclock.py` with six failing and six passing changes, Amendment 4a enabled;
- `scen`: `scenarios.py`;
- `cancel`: `cancelprobe.py --tag heldout6`;
- `perf`: `perf6.py`, then `perf6.py --host`.
"""

from __future__ import annotations

import json
import shlex
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import wallclock as W  # noqa: E402


def native_truth(name: str) -> None:
    """Amendment 5a: each change's label from the native full suite in the
    project's image (exit 0 at the base, non-zero with the change)."""
    import shutil
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor
    if not (H.out_dir(name) / "setup.json").exists():
        H.setup(name)
    if not (H.out_dir(name) / "changes.json").exists():
        H.gen_changes(name)
    runner = H.runner_for(name)
    tool = "node" if H.CORPUS[name]["lang"] == "node" else "python"

    def suite(work: Path) -> dict:
        ws = isolate.materialize(work, label="h6-native")
        try:
            ex = Executor(H.backend_for(name), work, python="python", node="node").in_workspace(ws)
            t = time.monotonic()
            res = ex.run(runner.full or shlex.split(runner.command), cwd=runner.cwd, env=runner.env, timeout_s=1800,
                         toolchain=tool)  # an opaque runner has no `full`: its own command
            return {"exit": res.exit_code, "timed_out": res.timed_out, "dur": round(time.monotonic() - t, 2),
                    "tail": (res.stdout + "\n" + res.stderr)[-400:]}
        finally:
            ws.cleanup()
    base_work = H._copy(name, "native-base")
    base = suite(base_work)
    shutil.rmtree(base_work, ignore_errors=True)
    out = {"_base": base}
    truth = {}
    for c in H.load(name, "changes"):
        work = H._copy(name, "native-" + c["id"])
        H._apply(work, c)
        r = suite(work)
        shutil.rmtree(work, ignore_errors=True)
        out[c["id"]] = r
        failing = base["exit"] == 0 and r["exit"] != 0 and not r["timed_out"]
        truth[c["id"]] = {"affected": ["<native suite>"] if failing else [],
                          "timeouts": ["<native suite>"] if r["timed_out"] else []}
        print(f"  {name} {c['id']}: exit {r['exit']} ({r['dur']}s)", flush=True)
    H.save(name, "native-truth", out)
    H.save(name, "truth", truth)
    H.save(name, "baseline", {})
    print(f"{name}: native base exit {base['exit']} ({base['dur']}s); "
          f"{sum(1 for v in truth.values() if v['affected'])}/{len(truth)} changes fail the native suite")


NODE_PATTERNS = ("**/*.test.?(c|m)", "**/*-test.?(c|m)", "**/*_test.?(c|m)", "**/test-*.?(c|m)", "**/test.?(c|m)",
                 "**/test/**/*.?(c|m)")


def node_files(name: str) -> None:
    """Amendment 5b: the harness universe of a `node --test` project is what
    node 24 itself runs with no paths (verify's own universe is untouched)."""
    from repo_ai.verify.runner import _glob_match
    repo = H.WORK / "repos" / name
    files = [f for f in H.git(repo, "ls-files").split("\n") if f]
    tests = sorted(f for f in files if "node_modules/" not in f and any(
        _glob_match(f, p + ext) for p in NODE_PATTERNS for ext in ("js", "ts")))
    meta = H.load(name, "setup")
    meta["tests"] = tests
    meta["universe_source"] = "Amendment 5b: node 24's default test patterns"
    H.save(name, "setup", meta)
    print(f"{name}: {len(tests)} test files by node's own default patterns")
    for fn in (H.baseline, H.truth, H.select_all):
        fn(name)


def main() -> int:
    step, names = sys.argv[1], sys.argv[2:]
    W.N_FAIL = W.N_PASS = 6  # Amendment 5 (also what perf6 measures: the same session changes)
    if step == "truth":
        for n in names:
            for fn in (H.build_image, H.setup, H.baseline, H.record, H.gen_changes, H.truth, H.select_all):
                fn(n)
    elif step == "node-files":  # Amendment 5b
        for n in names:
            node_files(n)
    elif step == "native-truth":  # Amendment 5a: no engine-listed test file, or the control
        for n in names:
            native_truth(n)
    elif step == "wall":
        os.environ["VEV_AMENDMENT_4A"] = "1"
        path = H.WORK / "wallclock-heldout6-new.json"
        results = json.loads(path.read_text()) if path.exists() else {}
        for n in names:
            print(f"== {n} at {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
            if n in results:
                results.setdefault("_superseded", []).append(results.pop(n))
            try:
                results[n] = W.measure("new", n)
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                results[n] = {"project": n, "engine": "new", "error": repr(exc)[:500]}
            print(json.dumps(results[n].get("summary") or results[n].get("error"), indent=1), flush=True)
            path.write_text(json.dumps(results, indent=1), "utf-8")
    elif step == "scen":
        import scenarios
        sys.argv = ["scenarios.py", *names]
        scenarios.main()
    elif step == "cancel":
        import cancelprobe
        sys.argv = ["cancelprobe.py", "--tag", "heldout6", *names]
        cancelprobe.main()
    elif step == "perf":
        import perf6
        sys.argv = ["perf6.py", *names]
        perf6.main()
        sys.argv = ["perf6.py", "--host", *names]
        perf6.main()
    else:
        raise SystemExit(f"unknown step {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
