"""c10-confirm-v1 harness (PREREGISTRATION.md, with Amendment 1).

    C10_WORK=<dir outside the repo> REPO_AI=<repo-ai executable> python run.py prepare
    C10_WORK=... python run.py run        # needs CLAUDE_CODE_OAUTH_TOKEN in the environment (token_env)
    C10_WORK=... python run.py grade

prepare: one project per run (fixture copy, git, `repo-ai init --agent none`, the skill installed in the skill arm),
order shuffled with a recorded seed. run: `claude -p` per run with a new empty CLAUDE_CONFIG_DIR (so nothing
user-level loads), stream kept. grade: oracle per run in a network-denied sandbox, in run-id order, arms looked up
afterwards; validity from each run's init event.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = Path(os.environ.get("C10_WORK", "")).resolve() if os.environ.get("C10_WORK") else None
REPO_AI = os.environ.get("REPO_AI", "repo-ai")
REPEATS = 3
TOOLS = "Read,Write,Edit,Glob,Grep,Skill"
CLEAN = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                                                           "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"}}
BUILTIN = json.loads((HERE / "probe" / "builtin-init-2.1.316.json").read_text())


def _skill_dir() -> Path:
    dirs = [d for d in (HERE / "skill").iterdir() if d.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def _tasks() -> list[dict]:
    return json.loads((HERE / "tasks.json").read_text())["tasks"]


def sh(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env or CLEAN, capture_output=True, text=True, check=True)


def prepare() -> None:
    assert WORK, "set C10_WORK"
    mapping = WORK / "mapping.json"
    assert not mapping.exists(), "already prepared"
    WORK.mkdir(parents=True, exist_ok=True)
    seed = secrets.randbits(32)
    skill = _skill_dir()
    runs = [{"task": t["id"], "arm": arm, "repeat": k} for t in _tasks() for arm in ("skill", "control")
            for k in range(REPEATS)]
    random.Random(seed).shuffle(runs)
    approve = ""
    for r in runs:
        rid = secrets.token_hex(4)
        r["id"] = rid
        proj = WORK / rid / "p"
        shutil.copytree(HERE / "fixture", proj)
        env = dict(CLEAN, REPO_AI_HOME=str(WORK / rid / "home"), REPO_AI_NO_BACKGROUND="1")
        sh(["git", "init", "-q", "-b", "main"], proj)
        sh(["git", "add", "-A"], proj)
        sh(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "base"], proj)
        sh([REPO_AI, "init", "--agent", "none", "-q"], proj, env)
        if r["arm"] == "skill":
            out = sh([REPO_AI, "skills", "discover", "--from-path", str(skill), "--json"], proj, env).stdout
            data = json.loads(out)
            hashes = {c.get("content_hash") for c in data.get("candidates", data.get("results", [])) if c.get("content_hash")}
            assert len(hashes) == 1, out[:400]
            approve = next(iter(hashes))
            sh([REPO_AI, "skills", "install", skill.name, "--approve", approve[:16], "--host", "claude-code"], proj, env)
            assert (proj / ".claude" / "skills" / skill.name / "SKILL.md").is_file()
    mapping.write_text(json.dumps({"seed": seed, "skill": skill.name, "approve": approve, "runs": runs}, indent=1))
    print("prepared", len(runs), "runs, seed", seed)


def run() -> None:
    assert WORK and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "set C10_WORK and CLAUDE_CODE_OAUTH_TOKEN"
    m = json.loads((WORK / "mapping.json").read_text())
    tasks = {t["id"]: t for t in _tasks()}
    for r in m["runs"]:
        out = WORK / r["id"] / "stream.jsonl"
        if out.exists():
            continue
        proj = WORK / r["id"] / "p"
        cfg = Path(tempfile.mkdtemp(prefix="c10cfg-"))  # new and empty for every run
        env = dict(CLEAN, CLAUDE_CONFIG_DIR=str(cfg))
        cmd = ["claude", "-p", tasks[r["task"]]["request"], "--model", "sonnet", "--tools", TOOLS,
               "--setting-sources", "project", "--strict-mcp-config", "--permission-mode", "acceptEdits",
               "--no-session-persistence", "--output-format", "stream-json", "--verbose", "--max-budget-usd", "0.30"]
        p = subprocess.run(cmd, cwd=proj, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=900)
        out.write_text(p.stdout)
        (WORK / r["id"] / "stderr.txt").write_text(p.stderr[-4000:])
        shutil.rmtree(cfg, ignore_errors=True)
        print(r["id"], "exit", p.returncode, flush=True)


def audit(rid: str, skill: str, arm: str) -> dict:
    proj = str((WORK / rid / "p").resolve())
    tools, outside, cost, result, init, invalid = [], [], None, None, None, []
    for line in (WORK / rid / "stream.jsonl").read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    tools.append(c["name"])
                    inp = c.get("input", {})
                    for key in ("file_path", "path"):
                        v = inp.get(key)
                        if v and not str(Path(proj, v).resolve()).startswith(proj):
                            outside.append(v)
        if ev.get("type") == "result":
            cost, result = ev.get("total_cost_usd"), ev.get("subtype")
    if init is None:
        invalid.append("no init event")
    else:
        allowed = set(BUILTIN["skills"]) | ({skill} if arm == "skill" else set())
        extra = sorted(set(init.get("skills") or []) - allowed)
        if extra:
            invalid.append(f"skills outside the allowed set: {extra}")
        if any(not str(p.get("source", "")).endswith("@builtin") for p in init.get("plugins") or []):
            invalid.append("a non-builtin plugin")
        if init.get("mcp_servers"):
            invalid.append("an MCP server")
        if set(init.get("tools") or []) - set(TOOLS.split(",")):
            invalid.append("a tool outside the list")
    return {"tools": tools, "outside": outside, "cost": cost, "result": result, "invalid": invalid,
            "skill_called": "Skill" in tools}


def _grade_profile(proj: Path, tmp: Path) -> str:
    q = json.dumps
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            f"(allow file-write* (subpath {q(str(proj))}))(allow file-write* (subpath {q(str(tmp))}))"
            '(allow file-write* (literal "/dev/null"))')


def grade_one(proj: Path, task_id: str) -> dict:
    oracle = HERE / "oracle" / f"test_{task_id}.py"
    target = proj / f"test_oracle_{task_id}.py"
    shutil.copyfile(oracle, target)
    tmp = Path(tempfile.mkdtemp(prefix="c10grade-"))
    env = dict(CLEAN, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp))
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "-rA", str(target.name)]
    if sys.platform == "darwin":
        cmd = ["/usr/bin/sandbox-exec", "-p", _grade_profile(proj.resolve(), tmp.resolve()), *cmd]
    p = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True, timeout=300)
    target.unlink(missing_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    passed = {line.split("::", 1)[1].split()[0] for line in p.stdout.splitlines()
              if line.startswith("PASSED ") and "::" in line}
    return {"passed": sorted(passed), "tail": p.stdout[-300:]}


def grade() -> None:
    m = json.loads((WORK / "mapping.json").read_text())
    spec = {t["id"]: t for t in _tasks()}
    rows = []
    for r in sorted(m["runs"], key=lambda r: r["id"]):  # graded in id order, before arms are looked up
        g = grade_one(WORK / r["id"] / "p", r["task"])
        conv = [a for a in spec[r["task"]]["assertions"] if a["kind"] == "convention"]
        base = [a for a in spec[r["task"]]["assertions"] if a["kind"] == "baseline"]
        rows.append({"id": r["id"], "task": r["task"], "repeat": r["repeat"],
                     "convention": sum(a["test"] in g["passed"] for a in conv) / len(conv) if conv else None,
                     "baseline": sum(a["test"] in g["passed"] for a in base) / len(base) if base else None,
                     "passed": g["passed"], **audit(r["id"], m["skill"], r["arm"])})
    arm_of = {r["id"]: r["arm"] for r in m["runs"]}
    for row in rows:
        row["arm"] = arm_of[row["id"]]
    (WORK / "results.json").write_text(json.dumps(rows, indent=1))
    valid = [r for r in rows if not r["invalid"]]
    higher = lower = 0
    per_task = {}
    for t in spec:
        means = {}
        for arm in ("skill", "control"):
            xs = [r["convention"] for r in valid if r["task"] == t and r["arm"] == arm and r["convention"] is not None]
            means[arm] = sum(xs) / len(xs) if xs else None
        if means["skill"] is None or means["control"] is None:
            per_task[t] = {**means, "diff": None}
            continue
        diff = means["skill"] - means["control"]
        per_task[t] = {**means, "diff": round(diff, 4)}
        higher += diff > 0
        lower += diff < 0
    n = higher + lower
    from math import comb
    p = sum(comb(n, k) for k in range(higher, n + 1)) / 2 ** n if n else 1.0
    verdict = ("SUPPORTED" if higher > lower and p < 0.05 else "NEGATIVE" if lower >= higher else "INCONCLUSIVE")
    summary = {"per_task": per_task, "skill_higher": higher, "control_higher": lower, "sign_test_p": round(p, 4),
               "verdict": verdict, "invalid": [r["id"] for r in rows if r["invalid"]],
               "cost": round(sum(r["cost"] or 0 for r in rows), 4)}
    (WORK / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    {"prepare": prepare, "run": run, "grade": grade}[sys.argv[1]]()
