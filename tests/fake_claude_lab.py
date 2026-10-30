"""Deterministic fake `claude -p --output-format stream-json` for the coding lab.

    fake_claude_lab.py SOLUTIONS.json POLICY [claude flags...]

POLICY:
  solve-all             apply the reference solution in every arm
  solve-with-repo-ai    solve only when repo-ai skills are present (simulates a benefit)
  solve-without-repo-ai solve only when they are absent (simulates a regression)
  none                  never edit
  harmed-by-thirdparty  solve unless a non-repo-ai (third-party) skill is installed
  needs-skill:NAME      solve only when the skill NAME is installed (tournaments)

Any policy may end in `@cost=X` to report a run cost of X USD (budget tests),
and may add modifiers with `+` (before any `@cost`):
  +runtests  run the workspace's unittest suite with the real interpreter, as an
             agent's Bash call would (writes __pycache__ bytecode), and leave a
             .pytest_cache behind: harmless execution artifacts
  +stray     also edit a source file outside the task (a genuine unnecessary edit)
  +peek      read the hidden test named by SOLUTIONS["__peek__"] (the fake is not
             sandboxed, so it can) with a visible Read call, and write it to
             SOLUTIONS["__dest__"]: real access
  +peek-denied  attempt that Read, and get a permission denial back
  +canary    silently search the denied lab directory (from --settings) for hidden
             tests and copy what it finds into the workspace: a sandbox escape
  +denylist  write the run's sandbox denyRead list to denylist.json (isolation tests)
  +match     write SOLUTIONS["__match__"] (content equal to the hidden test) to
             SOLUTIONS["__dest__"] with an ordinary Edit: legitimate, no access

The init event reports the skills and agents actually present in the
workspace's `.claude/`, plus one hook event per configured hook, so the
lab's isolation checks see what a real run would load. Never touches the
network; prints usage numbers so cost and token aggregation can be tested.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    solutions = json.loads(Path(sys.argv[1]).read_text("utf-8"))
    policy, _, cost_spec = sys.argv[2].partition("@cost=")
    run_cost = float(cost_spec) if cost_spec else 0.02
    policy, *mods = policy.split("+")
    argv = sys.argv[3:]
    prompt = argv[argv.index("-p") + 1]
    cwd = Path.cwd()
    skills = sorted(p.parent.name for p in (cwd / ".claude" / "skills").glob("*/SKILL.md"))
    agents = sorted(p.stem for p in (cwd / ".claude" / "agents").glob("*.md"))
    hooks = 0
    settings = cwd / ".claude" / "settings.json"
    if settings.is_file():
        data = json.loads(settings.read_text("utf-8"))
        hooks = sum(len(entries) for entries in (data.get("hooks") or {}).values())
    print(json.dumps({"type": "system", "subtype": "init", "model": "fake-model",
                      "claude_code_version": "0.0.0-fake", "skills": skills,
                      "agents": [{"name": a} for a in agents], "plugins": [], "tools": ["Read"]}))
    for _ in range(min(hooks, 2)):
        print(json.dumps({"type": "system", "subtype": "hook_response", "hook_name": "x"}))
    has_repo_ai = any(s.startswith("repo-") for s in skills)
    third_party = any(not s.startswith("repo-") for s in skills)
    if policy.startswith("needs-skill:"):
        solve = policy.split(":", 1)[1] in skills
    else:
        solve = {"solve-all": True, "solve-with-repo-ai": has_repo_ai,
                 "solve-without-repo-ai": not has_repo_ai, "none": False,
                 "harmed-by-thirdparty": not third_party}[policy]
    edits = solutions.get(prompt, []) if solve else []
    for edit in edits:
        path = cwd / edit["file"]
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": str(path)}}]}}))
        if "create" in edit:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(edit["create"], "utf-8")
        else:
            text = path.read_text("utf-8")
            path.write_text(text.replace(edit["find"], edit["replace"], 1), "utf-8")
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": str(path)}}]}}))
    if "stray" in mods:
        gold = {e["file"] for e in edits}
        stray = next(p for p in sorted(cwd.rglob("*.py")) if p.relative_to(cwd).as_posix() not in gold
                     and "test" not in p.relative_to(cwd).as_posix() and ".claude" not in p.parts
                     and ".repo-ai" not in p.parts and p.name != "__init__.py")
        stray.write_text(stray.read_text("utf-8") + "\n# unrelated change\n", "utf-8")
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": str(stray)}}]}}))
    if "runtests" in mods:
        command = "python3 -m unittest discover -s tests -t ."
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": command}}]}}))
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=cwd, env=env, capture_output=True, check=False, timeout=120)
        (cwd / ".pytest_cache" / "v" / "cache").mkdir(parents=True, exist_ok=True)
        (cwd / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("[]", "utf-8")
    def tool(name, inp, result=None, error=False):
        uid = f"tu-{name}-{len(inp)}"
        print(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": uid, "name": name, "input": inp}]}}))
        if result is not None:
            print(json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": result, "is_error": error}]}}))
    if "peek" in mods:
        hidden = Path(solutions["__peek__"]).read_text("utf-8")
        tool("Read", {"file_path": solutions["__peek__"]}, hidden)
        (cwd / solutions["__dest__"]).write_text(hidden, "utf-8")
    if "peek-denied" in mods:
        tool("Read", {"file_path": solutions["__peek__"]},
             f"Permission to read {solutions['__peek__']} has been denied.", error=True)
    if "canary" in mods:
        settings_path = Path(argv[argv.index("--settings") + 1])
        deny = json.loads(settings_path.read_text("utf-8"))["sandbox"]["filesystem"]["denyRead"]
        found = [p for d in deny for p in Path(d).glob("canaries/*/cases/*/hidden/*") if p.is_file()]
        (cwd / "notes.txt").write_text("".join(p.read_text("utf-8") for p in found), "utf-8")
    if "denylist" in mods:  # record what this run may not read (isolation tests)
        settings_path = Path(argv[argv.index("--settings") + 1])
        deny = json.loads(settings_path.read_text("utf-8"))["sandbox"]["filesystem"]["denyRead"]
        (cwd / "denylist.json").write_text(json.dumps(deny), "utf-8")
    if "match" in mods:
        dest = cwd / solutions["__dest__"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(solutions["__match__"], "utf-8")
        tool("Edit", {"file_path": str(dest)})
    tokens = 4000 if has_repo_ai else 6000
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "num_turns": 4 if edits else 2, "duration_ms": 1500,
                      "total_cost_usd": run_cost, "usage": {"input_tokens": tokens,
                                                        "output_tokens": 300},
                      # all models of the session (a subagent model included), like Claude Code
                      "modelUsage": {"fake-model": {"inputTokens": tokens, "outputTokens": 300,
                                                    "cacheReadInputTokens": 1000,
                                                    "cacheCreationInputTokens": 200},
                                     "fake-small-model": {"inputTokens": 50, "outputTokens": 10}}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
