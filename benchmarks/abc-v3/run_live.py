"""Live runner for abc-v3 (arms A, B and C).  Arm C = `repo-ai do --tournament codex,agy` (abstains unless exactly one distinct passing candidate).

Usage: python run_live.py --out DIR --task py-template --arm A|B|C --provider codex|bob  (arm C ignores --provider: codex+agy) [--max-usd 0.5] [--max-seconds 600]

Codex has no hard USD flag: its runs are bounded by --max-seconds and cost is recorded as UNKNOWN.

* Each run starts from a fresh git copy of tasks/<id>/repo (hidden/ is never copied).
* Arm A: `bob run` with the task prompt as-is, same flags/HOME-isolation as repo-ai's adapter
        but no repo-ai wrapper, no write-path constraint text, no frozen verification.
* Arm B: `repo-ai do "<prompt>" --agent bob --allow-live-provider --run`.
* Grading: candidate = write_paths files in the agent's resulting tree (A) / the mission's
        stored diff applied to a fresh copy (B); graded by grade.py in a separate temp dir.
* Every attempt is appended to DIR/runs.jsonl, including failures; nothing is retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grade  # noqa: E402


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


def fresh_repo(task_id: str, dest: Path) -> Path:
    shutil.copytree(HERE / "tasks" / task_id / "repo", dest)
    _git(dest, "init", "-q")
    _git(dest, "config", "user.email", "abc@example.invalid")
    _git(dest, "config", "user.name", "abc")
    (dest / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.repo-ai/\nnode_modules/\n")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "baseline")
    return dest


def run_a(task, repo: Path, max_usd: float, max_s: int, provider: str = "bob") -> dict:
    if provider == "codex":
        return run_a_codex(task, repo, max_s)
    from repo_ai.providers.adapters import parse_event_stream
    with tempfile.TemporaryDirectory(prefix="abc-armA-") as d:
        home = Path(d) / "home"
        (home / ".bob").mkdir(parents=True)
        src = Path.home() / ".bob" / "settings"
        if src.is_dir():
            shutil.copytree(src, home / ".bob" / "settings")
        (Path(d) / "tmp").mkdir()
        bob_dir = str(Path(shutil.which("bob")).parent)
        env = {"PATH": os.pathsep.join(["/usr/bin", "/bin", bob_dir, str(Path(sys.executable).resolve().parent)]),
               "HOME": str(home), "TMPDIR": str(Path(d) / "tmp"), "CI": "1", "NO_COLOR": "1", "TERM": "dumb"}
        for k in ("BOB_API_KEY", "USER"):  # same auth vars repo-ai's adapter forwards; BOB_SESSION is NOT forwarded
            if os.environ.get(k):
                env[k] = os.environ[k]
        argv = ["bob", "run", "--format", "json", "--trust", "--disable-mcp", "--disable-subagents",
                "--max-turns", "8", "--workspace", str(repo), "--max-cost", f"{max_usd:.4f}", task["prompt"]]
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=max_s)
            rc, out = p.returncode, p.stdout
        except subprocess.TimeoutExpired as e:
            rc = "timeout"
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    ev = parse_event_stream("bob", out.encode())
    cost = ev.get("cost_usd") if ev.get("cost_status") == "OBSERVED" else None
    cand = {rel: (repo / rel).read_text() for rel in task["write_paths"] if (repo / rel).exists()}
    changed = _git(repo, "status", "--porcelain").splitlines()
    return {"returncode": rc, "wall_s": round(time.time() - t0, 1), "observed_usd": cost,
            "cost_status": ev.get("cost_status"), "candidate": cand, "changed_paths": changed,
            "agent_count": 1, "human_interventions": 0}


def run_a_codex(task, repo: Path, max_s: int) -> dict:
    """Arm A for codex: its ordinary `codex exec` workflow in the task repo with codex's own workspace-write sandbox,
    scratch HOME (same auth files repo-ai seeds), the raw task prompt, no repo-ai wrapper."""
    from repo_ai.providers.adapters import _seed_live_provider_auth, parse_event_stream
    with tempfile.TemporaryDirectory(prefix="abc-armA-codex-") as d:
        home = Path(d) / "home"
        (home / ".codex").mkdir(parents=True)
        _seed_live_provider_auth("codex", home)
        (Path(d) / "tmp").mkdir()
        codex_dir = str(Path(shutil.which("codex")).parent)
        env = {"PATH": os.pathsep.join(["/usr/bin", "/bin", codex_dir, str(Path(sys.executable).resolve().parent)]),
               "HOME": str(home), "TMPDIR": str(Path(d) / "tmp"), "CODEX_HOME": str(home / ".codex"),
               "CI": "1", "NO_COLOR": "1", "TERM": "dumb"}
        if os.environ.get("USER"):
            env["USER"] = os.environ["USER"]
        argv = ["codex", "exec", "--json", "--ephemeral", "--sandbox", "workspace-write", "-C", str(repo), task["prompt"]]
        t0 = time.time()
        try:
            p = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=max_s, stdin=subprocess.DEVNULL)
            rc, out = p.returncode, p.stdout
        except subprocess.TimeoutExpired as e:
            rc = "timeout"
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    ev = parse_event_stream("codex", out.encode())
    cand = {rel: (repo / rel).read_text() for rel in task["write_paths"] if (repo / rel).exists()}
    changed = _git(repo, "status", "--porcelain").splitlines()
    return {"returncode": rc, "wall_s": round(time.time() - t0, 1), "observed_usd": None,
            "cost_status": "UNKNOWN", "tokens": ev.get("tokens"), "candidate": cand, "changed_paths": changed,
            "agent_count": 1, "human_interventions": 0}


def run_b(task, repo: Path, max_usd: float, max_s: int, out: Path, provider: str = "bob") -> dict:
    argv = [sys.executable, "-m", "repo_ai", "do", task["prompt"], "-C", str(repo), "--agent", provider,
            "--allow-live-provider", "--run", "--json", "--max-cost-usd", f"{max_usd if provider == 'bob' else 0:.4f}",
            "--max-seconds", str(max_s), "--test-command", task["test_command"]]
    for w in task["write_paths"]:
        argv += ["--allow-write", w]
    t0 = time.time()
    p = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=max_s + 300)
    wall = round(time.time() - t0, 1)
    try:
        m = json.loads(p.stdout)
    except Exception:
        return {"returncode": p.returncode, "wall_s": wall, "observed_usd": None, "candidate": {},
                "mission_parse_error": p.stdout[:300], "stderr_tail": p.stderr[-300:], "agent_count": 1}
    (out / "missions").mkdir(exist_ok=True)
    (out / "missions" / f"{task['id']}-{int(time.time())}.json").write_text(p.stdout)
    diff = m.get("diff") or ""
    if diff and not diff.endswith("\n"):
        diff += "\n"  # mission JSON strips the final newline; git apply needs it
    cand = {}
    if diff:
        with tempfile.TemporaryDirectory(prefix="abc-armB-") as d:
            w = fresh_repo(task["id"], Path(d) / "w")
            ap = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=w, input=diff,
                                capture_output=True, text=True)
            apply_err = ap.stderr[-200:] if ap.returncode else None
            if ap.returncode == 0:
                cand = {rel: (w / rel).read_text() for rel in task["write_paths"] if (w / rel).exists()}
    prov = m.get("provider") or {}
    return {"returncode": p.returncode, "wall_s": wall, "mission_id": m.get("id"),
            "repo_ai_verdict": m.get("effective_verdict"),
            "abstained": not diff,
            "observed_usd": prov.get("cost_usd") if prov.get("cost_status") == "OBSERVED" else None,
            "cost_status": prov.get("cost_status"),
            "candidate": cand, "agent_count": 1, "human_interventions": 0,
            "diff_chars": len(diff), "diff_apply_error": locals().get("apply_err")}


def run_c(task, repo: Path, max_s: int, out: Path) -> dict:
    """Arm C: live two-provider tournament (codex, agy). Candidate = the winner's stored diff; abstention => no candidate."""
    argv = [sys.executable, "-m", "repo_ai", "do", task["prompt"], "-C", str(repo), "--tournament", "codex,agy",
            "--allow-live-provider", "--run", "--json", "--max-seconds", str(max_s),
            "--test-command", task["test_command"]]
    for w in task["write_paths"]:
        argv += ["--allow-write", w]
    t0 = time.time()
    p = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=2 * max_s + 300)
    wall = round(time.time() - t0, 1)
    try:
        m = json.loads(p.stdout)
    except Exception:
        return {"returncode": p.returncode, "wall_s": wall, "observed_usd": None, "candidate": {},
                "mission_parse_error": p.stdout[:300], "stderr_tail": p.stderr[-300:], "agent_count": 2}
    (out / "missions").mkdir(exist_ok=True)
    (out / "missions" / f"{task['id']}-C-{int(time.time())}.json").write_text(p.stdout)
    cand, apply_err, diff = {}, None, ""
    winner = m.get("winner")
    if winner:
        from repo_ai.mission.runtime import status
        diff = (status(repo.resolve(), winner).get("diff") or "")
        if diff and not diff.endswith("\n"):
            diff += "\n"
        with tempfile.TemporaryDirectory(prefix="abc-armC-") as d:
            w = fresh_repo(task["id"], Path(d) / "w")
            ap = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=w, input=diff, capture_output=True, text=True)
            apply_err = ap.stderr[-200:] if ap.returncode else None
            if ap.returncode == 0:
                cand = {rel: (w / rel).read_text() for rel in task["write_paths"] if (w / rel).exists()}
    per_arm = []  # secondary record only: what each arm would have scored alone. Never the arm C outcome.
    from repo_ai.mission.runtime import status as _status
    for c in m.get("candidates", []):
        try:
            cdiff = (_status(repo.resolve(), c["id"]).get("diff") or "")
            cdiff = cdiff + "\n" if cdiff and not cdiff.endswith("\n") else cdiff
            with tempfile.TemporaryDirectory(prefix="abc-armC-solo-") as d:
                w = fresh_repo(task["id"], Path(d) / "w")
                ok = bool(cdiff) and subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=w, input=cdiff,
                                                    capture_output=True, text=True).returncode == 0
                solo = {rel: (w / rel).read_text() for rel in task["write_paths"] if (w / rel).exists()} if ok else {}
            per_arm.append({"provider": c.get("provider"), "repo_ai": c.get("verdict"),
                            "graded": grade.grade(task["id"], solo)["outcome"] if solo else "NO_CANDIDATE"})
        except Exception as e:  # noqa: BLE001 - secondary record must not break the run
            per_arm.append({"provider": c.get("provider"), "error": str(e)[:120]})
    return {"returncode": p.returncode, "wall_s": wall, "mission_id": m.get("id"), "repo_ai_verdict": m.get("verdict"),
            "abstained": not winner, "winner": winner, "observed_usd": None, "cost_status": "UNKNOWN",
            "arm_verdicts": [(c.get("provider"), c.get("verdict")) for c in m.get("candidates", [])],
            "per_arm_secondary": per_arm,
            "candidate": cand, "agent_count": 2, "human_interventions": 0, "diff_chars": len(diff),
            "diff_apply_error": apply_err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--arm", required=True, choices=["A", "B", "C"])
    ap.add_argument("--provider", required=True, choices=["codex", "bob", "agy"])
    ap.add_argument("--max-usd", type=float, default=0.5)
    ap.add_argument("--max-seconds", type=int, default=600)
    a = ap.parse_args()
    if not 0 < a.max_usd <= 10:
        sys.exit("per-call cap must be in (0, 10]")
    if a.arm == "C":
        a.provider = "codex+agy"
    if a.arm == "A" and a.provider == "agy":
        sys.exit("arm A is not implemented for agy (its ordinary workflow is not sandboxed by this runner); arm B only")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    task = grade.load_task(a.task)
    with tempfile.TemporaryDirectory(prefix=f"abc-{a.arm}-{a.task}-") as d:
        repo = fresh_repo(a.task, Path(d) / "repo")
        if a.arm == "A":
            res = run_a(task, repo, a.max_usd, a.max_seconds, a.provider)
        elif a.arm == "B":
            res = run_b(task, repo, a.max_usd, a.max_seconds, out, a.provider)
        else:
            res = run_c(task, repo, a.max_seconds, out)
    cand = res.pop("candidate")
    g = grade.grade(a.task, cand) if cand else {"outcome": "ABSTAIN" if res.get("abstained") else "NO_CANDIDATE", "visible": None, "hidden": None, "ignored_paths": []}
    rec = {"task": a.task, "arm": a.arm, "provider": a.provider, "ceiling_usd": a.max_usd, **res,
           "graded": g, "candidate_sha": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in cand.items()},
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with (out / "runs.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("task", "arm", "wall_s", "observed_usd")} | {"outcome": g["outcome"]}))


if __name__ == "__main__":
    main()
