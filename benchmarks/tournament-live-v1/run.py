"""tournament-live-v1 harness (PREREGISTRATION.md): live Codex-vs-Claude tournaments on the abc-v5 calibration
tasks, each arm graded by abc-v5's sealed hidden oracle inside a podman container (the grader never runs model-written
code on the host; repo-ai's own verification and the providers run in repo-ai's host sandbox). At most 8 provider sessions in total, counted in a ledger at a fixed path under HOME; a task with a started
tournament is never run again, whatever --work is.

    python run.py --work DIR [--only cal-py-backoff] [--dry-run]

The repo-ai checkout this file lives in and DIR must both be under HOME (the provider sandboxes cannot read HOME on
macOS, and the hidden tests live in the checkout). --dry-run runs the preflight (plan-only tournament, grader
container on every reference and a decoy) and starts no provider. A run killed hard leaves the lock file
(LEDGER.lock); remove it by hand after checking no run is active.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ABC = ROOT / "benchmarks" / "abc-v5"
sys.path.insert(0, str(ABC))
import grade as G  # noqa: E402  (abc-v5's sealed grader: tasks, frozen bases, seal)

TASKS = ["cal-py-backoff", "cal-py-sizes", "cal-node-roman", "cal-node-chunk"]
# Codex first: its cost is UNKNOWN and never adds to the observed spend, so Claude's arm always gets its whole cap,
# and a Claude overshoot cannot exhaust the aggregate before Codex runs
PROVIDERS = "codex,claude"
CLAUDE_CAP = "1.50"  # the only provider here that enforces a ceiling gets all of it
MAX_SESSIONS = 8
LEDGER = Path.home() / ".local" / "share" / "repo-ai-studies" / "tournament-live-v1.jsonl"
GRADER_IMAGE = "localhost/tl1-grader:1"  # built from ./Containerfile: python:3.12-slim (digest-pinned), Debian nodejs, pytest
LABELS = ("CORRECT", "FALSE_GREEN", "FAIL")


class Log:
    def __init__(self, work: Path) -> None:
        self.path = work / "records.jsonl"

    def __call__(self, task: str, step: str, **data) -> dict:
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "task": task, "step": step, **data}
        for path in (self.path, LEDGER) if step in ("tournament-start", "tournament") else (self.path,):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"[{task}] {step}: " + json.dumps({k: v for k, v in data.items() if k not in ("record", "stderr")})[:300])
        return row


def ledger() -> list[dict]:
    return [json.loads(x) for x in LEDGER.read_text().splitlines()] if LEDGER.exists() else []


def repo_ai(*args: str, cwd: Path, timeout: float = 3600) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                                                            "OPENAI_API_KEY", "AI_AGENT", "CLAUDECODE",
                                                            "CLAUDE_CODE_ENTRYPOINT")}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, "-m", "repo_ai", *args], cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:  # stop repo-ai and everything it started, then record; never retried
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            out, err = proc.communicate(timeout=30)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        return {"argv": list(args), "exit": None, "timed_out": True, "record": None, "stderr": (err or "")[-2000:]}
    try:
        record = json.loads(out)
    except ValueError:
        record = None
    return {"argv": list(args), "exit": proc.returncode, "record": record, "stderr": (err or "")[-2000:]}


def frozen_repo(task_id: str, dest: Path) -> None:
    G.materialize_w(task_id, dest)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "frozen base"]):
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *cmd], cwd=dest, check=True, capture_output=True,
                       env=env)


def tournament_argv(task: dict, run: bool) -> list[str]:
    return ["do", task["prompt"], "--tournament", PROVIDERS, *(["--run", "--allow-live-provider"] if run else []),
            "--max-cost-usd", CLAUDE_CAP, "--allow-unknown-cost", "--test-command", task["test_command"],
            "--max-seconds", "1200", "--json", *[a for w in task["write_paths"] for a in ("--allow-write", w)]]


def grader_image() -> str | None:
    """The grader image's id, built from ./Containerfile when missing (network only while building)."""
    shown = subprocess.run(["podman", "image", "inspect", "--format", "{{.Id}}", GRADER_IMAGE], capture_output=True,
                           text=True)
    if shown.returncode != 0:
        subprocess.run(["podman", "build", "-q", "-t", GRADER_IMAGE, "-f", str(HERE / "Containerfile"), str(HERE)],
                       capture_output=True, text=True, timeout=1800)
        shown = subprocess.run(["podman", "image", "inspect", "--format", "{{.Id}}", GRADER_IMAGE],
                               capture_output=True, text=True)
    return shown.stdout.strip() if shown.returncode == 0 else None


def preflight(work: Path, log: Log) -> bool:
    """No provider starts. The build has --allow-unknown-cost (plan-only tournament: both providers eligible, the cap
    splits as preregistered) and the difference classification; the grader container grades every task's reference
    CORRECT and its first semantic decoy FALSE_GREEN."""
    task = G.load_task(TASKS[0])
    with tempfile.TemporaryDirectory(prefix="tl1-preflight-", dir=work) as tmp:
        repo = Path(tmp) / "repo"
        frozen_repo(TASKS[0], repo)
        res = repo_ai(*tournament_argv(task, run=False), cwd=repo, timeout=300)
    plan = res["record"] or {}
    split = (plan.get("bounds") or {}).get("per_arm_cost_usd_by_provider")
    eligible = {k: v.get("eligible") for k, v in (plan.get("readiness") or {}).items()}
    has_difference = (ROOT / "src" / "repo_ai" / "mission" / "difference.py").is_file()
    image = grader_image()
    controls = {}
    if image:
        for task_id in TASKS:
            cands = G.load_candidates(task_id)
            decoy = next((n for n in cands if n.startswith("decoy-")), None)
            controls[task_id] = {name: grade_in_container(task_id, G.candidate_files(task_id, name))["label"]
                                 for name in ("reference", decoy) if name}
    graded_ok = bool(image) and all(c.get("reference") == "CORRECT" and all(v == "FALSE_GREEN" for k, v in c.items()
                                                                           if k != "reference")
                                    for c in controls.values()) and len(controls) == len(TASKS)
    ok = (split == {"claude": 1.5, "codex": 0.0} and eligible == {"claude": True, "codex": True} and has_difference
          and graded_ok)
    log("all", "preflight", ok=ok, split=split, eligible=eligible, difference_classification=has_difference,
        grader_image=image, grader_controls=controls, exit=res["exit"], stderr=res["stderr"] if not ok else "")
    return ok


def grade_in_container(task_id: str, files: dict[str, str]) -> dict:
    """abc-v5's grader, run in a podman container without network: the candidate's code never runs on the host."""
    with tempfile.TemporaryDirectory(prefix="tl1-cand-", dir=Path.home() / ".cache") as tmp:
        cand = Path(tmp)
        for rel, text in files.items():
            (cand / rel).parent.mkdir(parents=True, exist_ok=True)
            (cand / rel).write_text(text, encoding="utf-8")
        code = ("import json, sys\nfrom pathlib import Path\nsys.path.insert(0, '/r/benchmarks/abc-v5')\n"
                "import grade as G\ng = G.grade(sys.argv[1], Path('/c'))\n"
                "print(json.dumps({'label': g.get('label'), 'reason': g.get('reason')}))\n")
        proc = subprocess.run(["podman", "run", "--rm", "--timeout", "880", "--network=none", "--read-only",
                               "--tmpfs", "/tmp",
                               "--cap-drop=all", "--security-opt", "no-new-privileges", "--pids-limit", "512",
                               "--memory", "2g", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1",
                               "-v", f"{ROOT}:/r:ro", "-v", f"{cand}:/c:ro", GRADER_IMAGE, "python", "-c", code,
                               task_id], capture_output=True, text=True, timeout=900)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"label": "HARNESS_ERROR", "reason": (proc.stderr or proc.stdout)[-400:]}


def candidate_files(task: dict, repo: Path, diff: str) -> dict[str, str] | None:
    """The candidate's write-path files: its diff applied to a clone of the frozen base (bytes, strict UTF-8)."""
    with tempfile.TemporaryDirectory(prefix="tl1-apply-") as tmp:
        copy = Path(tmp) / "c"
        if subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "-q", str(repo), str(copy)],
                          capture_output=True).returncode != 0:
            return None
        if subprocess.run(["git", "apply", "-"], cwd=copy, input=diff.encode(), capture_output=True).returncode != 0:
            return None
        try:
            return {rel: (copy / rel).read_bytes().decode("utf-8") for rel in task["write_paths"]
                    if (copy / rel).is_file()}
        except UnicodeDecodeError:
            return None


def run(work: Path, tasks: list[str], dry: bool, log: Log) -> None:
    G.verify_seal()
    if not preflight(work, log):
        raise SystemExit("preflight failed (see records): no provider was started")
    if dry:
        return
    for task_id in tasks:
        started = [r for r in ledger() if r["step"] == "tournament-start"]
        if any(r["task"] == task_id for r in started):
            log(task_id, "skipped", why="a tournament was already started for this task (never repeated)")
            continue
        if 2 * (len(started) + 1) > MAX_SESSIONS:
            log(task_id, "skipped", why="the approved 8 sessions would be exceeded")
            continue
        task = G.load_task(task_id)
        repo = work / task_id / "repo"
        if repo.exists():
            raise SystemExit(f"{repo} exists from an earlier invocation; the ledger keeps tasks from repeating")
        frozen_repo(task_id, repo)
        log(task_id, "tournament-start", sessions_before=2 * len(started))
        res = repo_ai(*tournament_argv(task, run=True), cwd=repo)
        report = res["record"] or {}
        log(task_id, "tournament", exit=res["exit"], timed_out=res.get("timed_out", False), record=report,
            stderr=res["stderr"] if not report else "")
        ids = [c["id"] for c in report.get("candidates", []) if c.get("id")]
        if not report or not ids:
            log(task_id, "stopped", why="no comparison or no candidate was recorded; stopping before the next task")
            break
        reference = {k: v for k, v in G.candidate_files(task_id, "reference").items() if k in task["write_paths"]}
        grades = {}
        for cand in report["candidates"]:
            if not cand.get("id"):
                continue
            try:
                state = repo_ai("mission", "status", cand["id"], "--json", cwd=repo)["record"] or {}
                diff = state.get("diff") or ""
                files = candidate_files(task, repo, diff) if diff else None
                graded = grade_in_container(task_id, files) if files is not None else {"label": "NO_CANDIDATE"}
            except Exception as exc:  # noqa: BLE001 - recorded per candidate; never loses the others
                files, graded = None, {"label": "HARNESS_ERROR", "reason": type(exc).__name__}
            grades[cand["id"]] = {"provider": cand.get("provider"), "verdict": cand.get("verdict"),
                                  "label": graded.get("label"), "reason": graded.get("reason"),
                                  "equals_reference": (files == reference) if files is not None else None}
        if any(g["label"] == "HARNESS_ERROR" for g in grades.values()):
            log(task_id, "grade-error", grades=grades, why="a grade failed in the harness; stopping before the next task")
            break
        winner = report.get("winner")
        passed = [c["id"] for c in report["candidates"] if c.get("verdict") == "PASS"]
        distinct = {c.get("diff_sha256") for c in report["candidates"] if c.get("verdict") == "PASS"}
        pairs = (report.get("differences") or {}).get("pairs", [])
        labelled = [p for p in pairs if all(grades.get(c, {}).get("label") in LABELS for c in p["candidates"])]
        t3 = [p for p in labelled if p["difference"] in ("IDENTICAL", "COSMETIC")
              and len({grades[c]["label"] for c in p["candidates"]}) > 1]
        step = report.get("next_step") or ""
        log(task_id, "graded", grades=grades, winner=winner,
            t1_arbitrary_winner=bool(winner) and not (winner in passed and len(distinct) == 1),
            t2_next_step_matches=bool(step) and ((f"repo-ai apply {winner}" in step) if winner
                                                 else not step.startswith("review the winner")
                                                 and not any(f"repo-ai apply {i}" in step for i in ids)),
            next_step=step, t3_violations=t3,
            t3_unlabelled_pairs=[p["candidates"] for p in pairs if p not in labelled],
            t4_winner_label=grades.get(winner, {}).get("label") if winner else None,
            r1=[{"pair": p["candidates"], "difference": p["difference"],
                 "labels": [grades.get(c, {}).get("label") for c in p["candidates"]]} for p in pairs])
        if report.get("id") and not winner:
            log(task_id, "shortlist", **repo_ai("shortlist", report["id"], "--json", cwd=repo))
    rows = [json.loads(x) for x in log.path.read_text().splitlines()]
    tour = [r for r in rows if r["step"] == "tournament"]
    graded = [r for r in rows if r["step"] == "graded"]
    claude = [c for r in tour for c in (r.get("record") or {}).get("candidates", []) if c.get("provider") == "claude"]
    log("all", "summary", tournaments=len(tour), grade_errors=[r["task"] for r in rows if r["step"] == "grade-error"], sessions_started=2 * len([r for r in ledger()
                                                                           if r["step"] == "tournament-start"]),
        t1_arbitrary_winners=sum(1 for r in graded if r["t1_arbitrary_winner"]),
        t2_mismatched_next_steps=sum(1 for r in graded if not r["t2_next_step_matches"]),
        t3_violations=sum(len(r["t3_violations"]) for r in graded),
        claude_cost_observed=round(sum(float(c["cost_usd"]) for c in claude if c.get("cost_usd") is not None), 4),
        claude_arms_cost_unknown=sum(1 for c in claude if c.get("id") and c.get("cost_usd") is None),
        codex_cost="UNKNOWN")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--only", action="append")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    home, work = Path.home().resolve(), args.work.resolve()
    if home not in work.parents or home not in ROOT.parents:
        raise SystemExit("the repo-ai checkout and --work must both be under HOME (the hidden tests live in the checkout)")
    work.mkdir(parents=True, exist_ok=True)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    lock = LEDGER.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"another run holds {lock}") from None
    try:
        run(work, args.only or TASKS, args.dry_run, Log(work))
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
