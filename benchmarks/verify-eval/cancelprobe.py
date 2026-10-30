#!/usr/bin/env python3
"""Cancellation probe (PROTOCOL.md Amendment 4): what is left after a
`verify --run` is stopped with SIGTERM while sandboxed tests run.

    VEV_WORK=... python cancelprobe.py [--tag T] <project> [...]

Per project, three times, in a fresh clone set up as `wallclock.py` does:
1. apply the first failing change (by the ground truth);
2. start `repo-ai verify --run --json --rerun` in the project's sandbox;
3. once a sandboxed test process exists (a `sandbox-exec`/`bwrap`
   descendant of the command, or a `repo-ai-*` container), wait 1.5 s and
   send SIGTERM to the command;
4. wait for it to exit, then 2 s more;
5. record:
   - the exit code (130 expected);
   - descendants seen before the signal that are still alive;
   - processes carrying a sandbox run marker that were not there before;
   - `repo-ai-*` containers that were not there before;
   - disposable workspaces created and not removed;
   - the clone's digest before and after.

The probe only signals the `repo-ai` process it started. Anything it finds
left over is reported, then killed (by pid or container name) so that one
project's leak does not affect the next.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import wallclock as W  # noqa: E402

RUNS = 3
DELAY_S = 1.5  # Amendment 4; `--delay S` only for runs labelled post-hoc


def _ps() -> list[tuple[int, int, str]]:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2] if len(parts) > 2 else ""))
    return rows


def _descendants(root: int) -> dict[int, str]:
    rows = _ps()
    kids: dict[int, list[tuple[int, str]]] = {}
    for pid, ppid, cmd in rows:
        kids.setdefault(ppid, []).append((pid, cmd))
    out, stack = {}, [root]
    while stack:
        for pid, cmd in kids.get(stack.pop(), []):
            out[pid] = cmd
            stack.append(pid)
    return out


def _marked() -> set[int]:
    """Processes of this user whose environment carries a sandbox run marker."""
    out = subprocess.run(["ps", "-axww", "-E", "-o", "pid=,uid=,command="], capture_output=True, text=True).stdout
    me = str(os.getuid())
    return {int(p[0]) for p in (ln.split(None, 2) for ln in out.splitlines())
            if len(p) == 3 and p[1] == me and p[0].isdigit() and "REPO_AI_SANDBOX_RUN=" in p[2]}


def _containers() -> set[str]:
    cli = shutil.which("podman") or shutil.which("docker")
    if not cli:
        return set()
    out = subprocess.run([cli, "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout
    return {n for n in out.split() if n.startswith("repo-ai-")}


def _workspaces() -> set[str]:
    from repo_ai.verify import isolate
    try:
        return {p.name for p in isolate.workspaces_root().iterdir()}
    except OSError:
        return set()


def probe(name: str) -> dict:
    src = H.WORK / "repos" / name
    repo = H.WORK / "cancel" / name
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    proj = H.CORPUS[name]
    sandbox_args = ["--sandbox", "podman"] + (["--image", proj["image"]] if proj.get("image") else []) \
        if proj.get("image") or name in W.PODMAN else []
    W.ra("new", repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "repo-ai init", check=False)
    truth = H.load(name, "truth")
    change = next((c for c in H.load(name, "changes") if (truth.get(c["id"]) or {}).get("affected")), None)
    if change is None:
        return {"project": name, "error": "no failing change in the ground truth"}
    runs = []
    for i in range(RUNS):
        H._apply(repo, change)
        before_digest = W.digest(repo)
        marked0, containers0, ws0 = _marked(), _containers(), _workspaces()
        cmd = [H.RA, "verify", "--run", "--json", "--rerun", "--test-command", proj["test_command"], *sandbox_args]
        t0 = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=repo, env=H.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        seen: dict[int, str] = {}
        started = None
        while proc.poll() is None and time.monotonic() - t0 < 600:
            now = _descendants(proc.pid)
            seen.update(now)
            if any(("sandbox-exec" in c or "bwrap" in c or " run " in c and "repo-ai-" in c) for c in now.values()) \
                    or _containers() - containers0:
                started = time.monotonic() - t0
                break
            time.sleep(0.05)
        row: dict = {"run": i, "test_process_seen_after_s": round(started, 2) if started is not None else None}
        if proc.poll() is None:
            time.sleep(DELAY_S)
            row["running_when_signalled"] = proc.poll() is None
            seen.update(_descendants(proc.pid))
            os.kill(proc.pid, signal.SIGTERM)
            try:
                proc.communicate(timeout=120)
                row["exit"] = proc.returncode
            except subprocess.TimeoutExpired:
                row["exit"] = "did not exit within 120 s after SIGTERM"
                proc.kill()
                proc.communicate()
        else:
            proc.communicate()
            row["exit"] = proc.returncode
            row["note"] = "the command finished before a test process was seen"
        time.sleep(2)
        alive = {p for p, _, _ in _ps()}
        row["survivors"] = sorted({p: c[:120] for p, c in seen.items() if p in alive}.values())
        row["new_marked_processes"] = sorted(_marked() - marked0)
        row["new_containers"] = sorted(_containers() - containers0)
        row["leftover_workspaces"] = sorted(_workspaces() - ws0)
        row["tree_unchanged"] = W.digest(repo) == before_digest
        row["clean"] = (row["exit"] == 130 and not row["survivors"] and not row["new_marked_processes"]
                        and not row["new_containers"] and not row["leftover_workspaces"] and row["tree_unchanged"])
        for pid in list(row["new_marked_processes"]) + [p for p in seen if p in alive]:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        cli = shutil.which("podman") or shutil.which("docker")
        for c in row["new_containers"]:
            subprocess.run([cli, "rm", "-f", c], capture_output=True)
        W._revert(repo)
        runs.append(row)
        print(f"  {name} run {i}: {json.dumps(row)[:300]}", flush=True)
    return {"project": name, "change": change["id"], "delay_s": DELAY_S, "runs": runs,
            "clean": all(r["clean"] for r in runs)}


def main() -> int:
    args = sys.argv[1:]
    tag = args[args.index("--tag") + 1] if "--tag" in args else "dev"
    global DELAY_S
    if "--delay" in args:
        DELAY_S = float(args[args.index("--delay") + 1])
    names = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in
                                                                         {"--tag", "--delay"})]
    path = H.WORK / f"cancelprobe-{tag}.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    for n in names:
        if n in results:
            results.setdefault("_superseded", []).append(results.pop(n))
        print(f"== {n} at {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
        try:
            results[n] = probe(n)
        except Exception as exc:  # noqa: BLE001 - recorded, not hidden
            results[n] = {"project": n, "error": repr(exc)[:500]}
        path.write_text(json.dumps(results, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
