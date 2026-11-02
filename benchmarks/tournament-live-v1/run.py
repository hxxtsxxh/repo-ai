"""tournament-live-v1 harness (PREREGISTRATION.md): live Claude-vs-Codex tournaments on the abc-v5 calibration
tasks, each arm graded by abc-v5's sealed hidden oracle. At most 8 provider sessions in total, counted from the
records; a task with a started tournament is never run again.

    python run.py --work DIR [--only cal-py-backoff] [--dry-run]

DIR must be under HOME (the provider sandboxes cannot read HOME on macOS). --dry-run runs everything except the
tournament (no provider starts).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ABC = ROOT / "benchmarks" / "abc-v5"
sys.path.insert(0, str(ABC))
import grade as G  # noqa: E402  (abc-v5's sealed grader)

TASKS = ["cal-py-backoff", "cal-py-sizes", "cal-node-roman", "cal-node-chunk"]
PROVIDERS = "claude,codex"
CLAUDE_CAP = "1.50"  # the only provider here that enforces a ceiling gets all of it
MAX_SESSIONS = 8


class Log:
    def __init__(self, work: Path) -> None:
        self.path = work / "records.jsonl"

    def rows(self) -> list[dict]:
        return [json.loads(x) for x in self.path.read_text().splitlines()] if self.path.exists() else []

    def __call__(self, task: str, step: str, **data) -> dict:
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "task": task, "step": step, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"[{task}] {step}: " + json.dumps({k: v for k, v in data.items() if k not in ("record", "stderr")})[:300])
        return row


def repo_ai(*args: str, cwd: Path, timeout: float = 3600) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                                                            "OPENAI_API_KEY", "AI_AGENT", "CLAUDECODE",
                                                            "CLAUDE_CODE_ENTRYPOINT")}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    try:
        proc = subprocess.run([sys.executable, "-m", "repo_ai", *args], cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return {"argv": list(args), "exit": None, "timed_out": True, "record": None,
                "stderr": (exc.stderr or b"")[-2000:].decode("utf-8", "replace") if isinstance(exc.stderr, bytes)
                else str(exc.stderr or "")[-2000:]}
    try:
        record = json.loads(proc.stdout)
    except ValueError:
        record = None
    return {"argv": list(args), "exit": proc.returncode, "record": record, "stderr": proc.stderr[-2000:]}


def frozen_repo(task_id: str, dest: Path) -> None:
    G.materialize_w(task_id, dest)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "frozen base"]):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *cmd], cwd=dest, check=True, capture_output=True,
                       env=env)


def candidate_files(task: dict, repo: Path, diff: str) -> dict[str, str] | None:
    """The candidate's write-path files: its diff applied to a copy of the frozen base."""
    with tempfile.TemporaryDirectory(prefix="tl1-cand-") as tmp:
        copy = Path(tmp) / "c"
        frozen_repo_copy = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "-q", str(repo),
                                           str(copy)], capture_output=True)
        if frozen_repo_copy.returncode != 0:
            return None
        applied = subprocess.run(["git", "apply", "-"], cwd=copy, input=diff.encode(), capture_output=True)
        if applied.returncode != 0:
            return None
        return {rel: (copy / rel).read_text("utf-8") for rel in task["write_paths"] if (copy / rel).is_file()}


def run(work: Path, tasks: list[str], dry: bool, log: Log) -> None:
    G.verify_seal()
    for task_id in tasks:
        history = log.rows()
        started = [r for r in history if r["step"] == "tournament-start"]
        if any(r["task"] == task_id for r in started):
            log(task_id, "skipped", why="a tournament was already started for this task (never repeated)")
            continue
        if 2 * (len(started) + 1) > MAX_SESSIONS:
            log(task_id, "skipped", why="the approved 8 sessions would be exceeded")
            continue
        task = G.load_task(task_id)
        repo = work / task_id / "repo"
        if repo.exists():
            raise SystemExit(f"{repo} exists; use a fresh --work directory")
        frozen_repo(task_id, repo)
        argv = ["do", task["prompt"], "--tournament", PROVIDERS, "--run", "--allow-live-provider", "--max-cost-usd",
                CLAUDE_CAP, "--allow-unknown-cost", "--test-command", task["test_command"], "--max-seconds", "1200",
                "--json", *[a for w in task["write_paths"] for a in ("--allow-write", w)]]
        if dry:
            log(task_id, "dry-run", argv=["repo-ai", *argv[:1], "<prompt>", *argv[2:]])
            continue
        log(task_id, "tournament-start", sessions_before=2 * len(started))
        res = repo_ai(*argv, cwd=repo)
        report = res["record"] or {}
        log(task_id, "tournament", exit=res["exit"], timed_out=res.get("timed_out", False), record=report,
            stderr=res["stderr"] if not report else "")
        grades = {}
        for cand in report.get("candidates", []):
            if not cand.get("id"):
                continue
            state = repo_ai("mission", "status", cand["id"], "--json", cwd=repo)["record"] or {}
            diff = state.get("diff") or ""
            files = candidate_files(task, repo, diff) if diff else None
            graded = G.grade(task_id, files) if files is not None else {"label": "NO_CANDIDATE"}
            reference = G.candidate_files(task_id, "reference")
            grades[cand["id"]] = {"provider": cand.get("provider"), "verdict": cand.get("verdict"),
                                  "label": graded.get("label"), "reason": graded.get("reason"),
                                  "equals_reference": files == {k: v for k, v in reference.items()
                                                                if k in task["write_paths"]} if files else None}
        winner = report.get("winner")
        passed = [c["id"] for c in report.get("candidates", []) if c.get("verdict") == "PASS"]
        distinct = {c.get("diff_sha256") for c in report.get("candidates", []) if c.get("verdict") == "PASS"}
        pairs = (report.get("differences") or {}).get("pairs", [])
        t3 = [p for p in pairs if p["difference"] in ("IDENTICAL", "COSMETIC")
              and len({grades.get(c, {}).get("label") for c in p["candidates"]}) > 1]
        log(task_id, "graded", grades=grades, winner=winner,
            t1_arbitrary_winner=bool(winner) and not (len(passed) == 1 or len(distinct) == 1),
            t2_next_step=bool(report.get("next_step")), next_step=report.get("next_step"),
            t3_violations=t3, t4_winner_label=grades.get(winner, {}).get("label") if winner else None,
            r1=[{"pair": p["candidates"], "difference": p["difference"],
                 "labels": [grades.get(c, {}).get("label") for c in p["candidates"]]} for p in pairs])
        if report.get("id") and not winner:
            log(task_id, "shortlist", **repo_ai("shortlist", report["id"], "--json", cwd=repo))
    rows = log.rows()
    tour = [r for r in rows if r["step"] == "tournament"]
    claude_cost = sum(float(c.get("cost_usd") or 0) for r in tour for c in (r.get("record") or {}).get("candidates", [])
                      if c.get("provider") == "claude" and c.get("cost_usd") is not None)
    log("all", "summary", tournaments=len(tour), claude_cost_observed=round(claude_cost, 4),
        codex_cost="UNKNOWN", sessions_started=2 * len([r for r in rows if r["step"] == "tournament-start"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--only", action="append")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    work = args.work.resolve()
    if Path.home().resolve() not in work.parents:
        raise SystemExit("--work must be under HOME")
    work.mkdir(parents=True, exist_ok=True)
    run(work, args.only or TASKS, args.dry_run, Log(work))
    return 0


if __name__ == "__main__":
    sys.exit(main())
