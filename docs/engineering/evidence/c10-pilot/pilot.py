"""C10 skill-value pilot harness (protocol predeclared in docs/engineering/EXPERIMENTS.md, commit 263b24d).

usage: pilot.py prepare | run | grade
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "c10run"
MAP = HERE / "mapping.json"
REPO_AI = HERE.parent / "public-repo/.venv/bin/repo-ai"
SKILL = HERE / "skill/invoicekit-conventions"
CLAUDE_DIR = Path.home() / ".local/share/repo-ai/claude-eval"
TASKS = {
    "t1": "In invoicekit/money.py add a function apply_discount(cents, percent) that returns the amount after taking "
    "`percent` percent off. Add a test for it.",
    "t2": "In invoicekit/lines.py add a function invoice_total(lines, tax_rate) that returns the invoice total "
    "including tax. `lines` is a list of (qty, unit_cents) tuples and tax_rate is a percentage such as 8.25. "
    "Add a test for it.",
    "t3": "In invoicekit/money.py add a function split_amount(cents, parts) that splits an amount into `parts` "
    "near-equal shares and returns them as a list. Add a test for it.",
}
CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}


def sh(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env or CLEAN_ENV, capture_output=True, text=True, check=True)


def prepare():
    assert not MAP.exists(), "already prepared"
    RUNS.mkdir()
    runs = []
    for task in TASKS:
        arms = ["skill", "control"]
        if secrets.randbelow(2):
            arms.reverse()
        for arm in arms:
            rid = secrets.token_hex(4)
            proj = RUNS / rid / "p"
            shutil.copytree(HERE / "base", proj)
            env = dict(CLEAN_ENV, REPO_AI_HOME=str(RUNS / rid / "home"))
            sh(["git", "init", "-q"], proj)
            sh(["git", "add", "-A"], proj)
            sh(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "base"], proj)
            sh([str(REPO_AI), "init", "--agent", "none", "-q"], proj, env)
            if arm == "skill":
                sh([str(REPO_AI), "skills", "discover", "--from-path", str(SKILL)], proj, env)
                sh([str(REPO_AI), "skills", "install", "invoicekit-conventions", "--approve", "ab942622969d0a1e",
                    "--host", "claude-code"], proj, env)
            runs.append({"id": rid, "task": task, "arm": arm})
    MAP.write_text(json.dumps(runs, indent=1))
    print("prepared", [(r["task"], r["id"]) for r in runs])


def run():
    for r in json.loads(MAP.read_text()):
        out = RUNS / r["id"] / "stream.jsonl"
        if out.exists():
            continue
        proj = RUNS / r["id"] / "p"
        env = dict(CLEAN_ENV, CLAUDE_CONFIG_DIR=str(CLAUDE_DIR))
        cmd = ["claude", "-p", TASKS[r["task"]], "--model", "haiku", "--setting-sources", "project",
               "--tools", "Read,Write,Edit,Glob,Grep,Skill", "--strict-mcp-config", "--permission-mode", "acceptEdits",
               "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--max-budget-usd", "0.30"]
        p = subprocess.run(cmd, cwd=proj, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=600)
        out.write_text(p.stdout)
        (RUNS / r["id"] / "stderr.txt").write_text(p.stderr)
        print(r["id"], "exit", p.returncode, flush=True)


def audit(rid):
    """Tool calls, skill use, paths outside the project, cost and result from one stream."""
    proj = str((RUNS / rid / "p").resolve())
    tools, outside, cost, result, init_skills = [], [], None, None, None
    for line in (RUNS / rid / "stream.jsonl").read_text().splitlines():
        ev = json.loads(line)
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init_skills = ev.get("skills")
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    tools.append(c["name"])
                    inp = c.get("input", {})
                    for key in ("file_path", "path"):
                        v = inp.get(key)
                        if v and not str(Path(proj, v).resolve()).startswith(proj):
                            outside.append(v)
        if ev.get("type") == "result":
            cost, result = ev.get("total_cost_usd"), ev.get("subtype")
    return {"tools": tools, "outside": outside, "cost": cost, "result": result,
            "skill_loaded": "invoicekit-conventions" in (init_skills or [])}


def grade():
    runs = json.loads(MAP.read_text())
    rows = []
    for r in sorted(runs, key=lambda r: r["id"]):  # graded by id, before looking at arms
        proj = RUNS / r["id"] / "p"
        oracle = subprocess.run([str(HERE / "grade.sh"), str(proj), r["task"]], capture_output=True, text=True).stdout
        visible = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no"],
                                 cwd=proj, capture_output=True, text=True).stdout.strip().splitlines()[-1:]
        rows.append({"id": r["id"], "task": r["task"], "oracle": oracle.strip(), "visible": visible,
                     **audit(r["id"])})
    by_id = {r["id"]: r for r in runs}
    for row in rows:
        row["arm"] = by_id[row["id"]]["arm"]
    (HERE / "results.json").write_text(json.dumps(rows, indent=1))
    wins = losses = 0
    for task in TASKS:
        score = {row["arm"]: int(row["oracle"].split("/")[0]) for row in rows if row["task"] == task}
        wins += score["skill"] > score["control"]
        losses += score["skill"] < score["control"]
        print(task, score)
    verdict = ("SUPPORTS VALUE" if wins >= 2 and losses == 0 else "NEGATIVE" if losses >= 2 else "INCONCLUSIVE")
    print("skill higher on", wins, "control higher on", losses, "->", verdict)
    for row in rows:
        print(row["task"], row["arm"], row["oracle"], row["visible"], "Skill" in row["tools"], row["cost"],
              row["result"], "outside:", row["outside"])


if __name__ == "__main__":
    {"prepare": prepare, "run": run, "grade": grade}[sys.argv[1]]()
