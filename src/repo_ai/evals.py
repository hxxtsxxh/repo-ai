"""Paired, held-out coding-task evaluation (`repo-ai eval`).

Two modes share one task suite (`benchmarks/tasks/`, shipped in the wheel):

* **offline** (default, free, deterministic): validates every task's oracle
  (hidden tests fail on the starting state, pass on the reference solution,
  visible tests keep passing, nothing leaks into the prompt or workspace),
  then measures how well repo-ai localizes the files a fix must touch, from
  the prompt alone. A naive lexical baseline is scored on the same tasks so
  the number means something.
* **live** (opt-in, billable): for each task, two fresh workspaces from the
  same commit run headless Claude Code (`claude -p`) with the same prompt,
  model, permissions and tools: one without repo-ai (control), one after
  `repo-ai init --agent claude --smart` (treatment). Hidden tests are copied
  in only after the agent exits. Arm order alternates by seed. Spending is
  hard-capped: a pair starts only if two worst-case runs still fit in the
  budget, and runs without cost data are charged at the cap.

Nothing here uploads code or logs. Transcripts are reduced to metrics in
memory; `--keep-artifacts` keeps workspaces locally for inspection.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from . import gitbin

SCHEMA_VERSION = 1
REQUIRED_TASK_KEYS = ("id", "base", "language", "category", "difficulty", "prompt", "setup",
                      "solution", "gold_files", "hidden", "commands")
CATEGORIES = {"bugfix", "feature", "refactor", "test", "api", "config", "ci", "integration",
              "monorepo"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "NotebookRead"}
SUBAGENT_TOOLS = {"Task", "Agent"}
MAX_BASH_RECORDED, BASH_COMMAND_CHARS = 100, 300
# the agent running a test suite (the allowed test runners, as Bash commands)
TEST_COMMAND = re.compile(r"(?:^|[;&|(\s])(?:python3?\s+-m\s+(?:unittest|pytest)|pytest|node\s+--test|"
                          r"npm\s+test|make\s+test|java\s+-cp)\b")
_STOP = frozenset(
    "the a an and or of to in on for with is are was be it this that when after before from "
    "by as at not no but if then so we our you your they them please fix bug add make should "
    "does doesnt dont can cant into out up down all any some there here what which who how why "
    "now also just like get gets got still only than more less very".split())


class SuiteError(ValueError):
    pass


# --------------------------------------------------------------------------
# suite
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Base:
    name: str
    language: str
    visible_tests: list[list[str]]
    toolchain: list[str]
    # third-party code (frozen open-source snapshots): run only in a sandbox
    third_party: bool = False
    source: str = ""
    license: str = ""


@dataclass(slots=True)
class Task:
    id: str
    base: str
    language: str
    category: str
    difficulty: str
    prompt: str
    setup: list[dict[str, str]]
    solution: list[dict[str, str]]
    gold_files: list[str]
    hidden: list[dict[str, str]]
    commands: list[list[str]]
    timeout_s: int
    attribution: str
    dir: Path
    split: str = ""  # explicit split ("final" = sealed test set); empty = by id hash
    # re-injected upstream bugs: the fix also updated existing test files, and
    # their pre-fix versions encode the bug. The regression check therefore runs
    # the whole suite with the updated files installed and ignores failures of
    # test methods *defined in* the hidden modules (see `regression_commands`)
    visible_after_hidden: bool = False


def default_suite_dir() -> Path:
    env = os.environ.get("REPO_AI_EVAL_SUITE")
    if env:
        return Path(env)
    source_tree = Path(__file__).resolve().parents[2] / "benchmarks" / "tasks"
    if (source_tree / "bases.json").is_file():
        return source_tree
    return Path(__file__).resolve().parent / "_evalsuite"


def load_suite(suite: Path) -> tuple[dict[str, Base], list[Task]]:
    meta_path = suite / "bases.json"
    if not meta_path.is_file():
        raise SuiteError(f"no task suite at {suite} (missing bases.json)")
    raw_bases = json.loads(meta_path.read_text("utf-8"))
    bases = {name: Base(name, b["language"], b["visible_tests"], b.get("toolchain", []),
                        bool(b.get("third_party", False)), str(b.get("source", "")),
                        str(b.get("license", "")))
             for name, b in raw_bases.items()}
    tasks: list[Task] = []
    seen: set[str] = set()
    for path in sorted((suite / "cases").glob("*/task.json")):
        data = json.loads(path.read_text("utf-8"))
        missing = [k for k in REQUIRED_TASK_KEYS if k not in data]
        if missing:
            raise SuiteError(f"{path.parent.name}: missing keys {missing}")
        if data["id"] in seen:
            raise SuiteError(f"duplicate task id {data['id']}")
        if data["base"] not in bases:
            raise SuiteError(f"{data['id']}: unknown base {data['base']}")
        seen.add(data["id"])
        tasks.append(Task(
            id=data["id"], base=data["base"], language=data["language"],
            category=data["category"], difficulty=data["difficulty"], prompt=data["prompt"],
            setup=list(data["setup"]), solution=list(data["solution"]),
            gold_files=list(data["gold_files"]), hidden=list(data["hidden"]),
            commands=[list(c) for c in data["commands"]],
            timeout_s=int(data.get("timeout_s", 120)),
            attribution=data.get("attribution", ""), dir=path.parent,
            split=str(data.get("split", "")),
            visible_after_hidden=bool(data.get("visible_after_hidden", False))))
        if tasks[-1].split not in ("", "dev", "holdout", *RESERVED_SPLITS):
            raise SuiteError(f"{data['id']}: unknown split {tasks[-1].split!r}")
    if not tasks:
        raise SuiteError(f"no tasks under {suite / 'cases'}")
    return bases, tasks


def split_of(task_id: str) -> str:
    """Deterministic dev/holdout split (by id hash, not by result). Tune
    ranking on `dev` only; `holdout` numbers are reported, never tuned on."""
    import hashlib
    return "dev" if int(hashlib.sha256(task_id.encode()).hexdigest(), 16) % 2 == 0 else "holdout"


def task_split(task: Task) -> str:
    return task.split or split_of(task.id)


# Splits that are never part of `all` and are selected only by name.
RESERVED_SPLITS = frozenset({"final", "calibration", "sealed-v2"})
# Sealed sets whose outcomes have been analysed: research/development
# evidence from now on, never a fresh holdout for changes they motivated.
ANALYZED_SPLITS = {
    "final": "analysed in the Option A experiment (2026-10-21, "
             "benchmarks/results/coding-option-a-v0.7.5.md); 0.7.6 changes were motivated by its "
             "results, so it is not fresh confirmatory evidence for them",
}


def select_tasks(tasks: list[Task], pattern: str | None, max_tasks: int | None,
                 seed: int, split: str = "all") -> list[Task]:
    """`all` means dev + holdout. The sealed sets (`final`, now analysed;
    `sealed-v2`, untouched) and `calibration` are only ever selected by name,
    so routine runs never touch them."""
    chosen = [t for t in tasks if (not pattern or re.search(pattern, t.id))
              and (task_split(t) == split if split != "all"
                   else task_split(t) not in RESERVED_SPLITS)]
    if max_tasks and len(chosen) > max_tasks:
        rng = random.Random(seed)
        chosen = sorted(rng.sample(chosen, max_tasks), key=lambda t: t.id)
    return chosen


# --------------------------------------------------------------------------
# workspaces
# --------------------------------------------------------------------------
def _safe_rel(rel: str) -> PurePosixPath:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise SuiteError(f"unsafe path in task: {rel!r}")
    return path


def apply_edits(ws: Path, edits: list[dict[str, str]], where: str) -> None:
    for edit in edits:
        target = ws / _safe_rel(edit["file"])
        if edit.get("delete"):  # a re-injected bug: the file only exists after the fix
            if target.is_file() and not target.is_symlink():
                target.unlink()
            continue
        if "create" in edit:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit["create"], encoding="utf-8", newline="")
            continue
        text = target.read_text("utf-8")
        count = text.count(edit["find"])
        if count != 1:
            raise SuiteError(f"{where}: `find` occurs {count} times in {edit['file']}")
        target.write_text(text.replace(edit["find"], edit["replace"], 1), encoding="utf-8",
                          newline="")


_GIT_ENV = {"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
            "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def _git(ws: Path, *args: str) -> None:
    subprocess.run([gitbin.git(), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false",
                    "-c", "gc.auto=0", "-c", "core.fsmonitor=false", *args],
                   cwd=ws, check=True, timeout=60, env={**os.environ, **_GIT_ENV},
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def materialize(task: Task, suite: Path, dest: Path, *, solved: bool = False,
                git: bool = True) -> Path:
    """Base + setup (+ solution) in `dest`, as a one-commit git repository.
    Hidden tests are never copied here."""
    # An installed suite is byte-compiled by pip: never copy __pycache__/*.pyc
    # into a workspace (they skew localization and would show compiled code).
    shutil.copytree(suite / "bases" / task.base, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"))
    apply_edits(dest, task.setup, f"{task.id} setup")
    if solved:
        apply_edits(dest, task.solution, f"{task.id} solution")
    if git:
        _git(dest, "init", "-q", "-b", "main")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-qm", "start")
    return dest


_REGRESSION_RUNNER = """
import os, sys, unittest
args = sys.argv[1:]
if args[0] == "--names":  # an explicit module list (run from a directory), then -- excluded
    split = args.index("--")
    os.chdir(args[1])
    sys.path.insert(0, os.getcwd())
    names, excluded = args[2:split], set(args[split + 1:])
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
else:
    start, top, excluded = args[0], args[1], set(args[2:])
    suite = unittest.defaultTestLoader.discover(start, top_level_dir=top)
result = unittest.TextTestRunner(verbosity=0, warnings="default").run(suite)  # as `python -m unittest`
def defined_in(test):
    method = getattr(type(test), getattr(test, "_testMethodName", ""), None)
    return getattr(method, "__module__", type(test).__module__)
bad = [t.id() for t, _ in result.failures + result.errors if defined_in(t) not in excluded]
for name in bad:
    print("REGRESSION", name)
sys.exit(1 if bad else 0)
"""


def regression_commands(task: Task, base: Base) -> list[list[str]]:
    """The visible regression check. For re-injected bugs: the whole unittest
    suite with the updated test files installed, ignoring failures of test
    methods defined in the hidden modules (those are the task, not regressions;
    inherited copies in other modules are ignored too)."""
    if not task.visible_after_hidden:
        return base.visible_tests
    argv = base.visible_tests[0]
    dests = [_safe_rel(i["dest"]).as_posix() for i in task.hidden]
    if argv[:2] == ["sh", "-c"] and len(argv) == 3:
        # sealed-v2 forms: `[cd DIR && ]python3 -m unittest MODULES` or `node --test FILES`
        py = re.fullmatch(r"(?:cd ([\w./-]+) && )?python3? -m unittest ((?:[\w.]+ ?)+)", argv[2].strip())
        if py:
            cwd = py.group(1) or "."
            rel = [d[len(cwd.rstrip("/")) + 1:] if cwd != "." and d.startswith(cwd.rstrip("/") + "/") else d
                   for d in dests]
            hidden = [PurePosixPath(d).with_suffix("").as_posix().replace("/", ".") for d in rel]
            return [["{python}", "-c", _REGRESSION_RUNNER, "--names", cwd, *py.group(2).split(), "--", *hidden]]
        node = re.fullmatch(r"node --test ((?:[\w./-]+ ?)+)", argv[2].strip())
        if node:  # whole hidden files are the task: the regression check is the rest
            rest = [f for f in node.group(1).split() if f not in dests]
            return [["sh", "-c", "node --test " + " ".join(rest)]] if rest else []
        return base.visible_tests
    if argv[:3] == ["{python}", "-m", "unittest"] and "discover" not in argv:
        hidden = [PurePosixPath(d).with_suffix("").as_posix().replace("/", ".") for d in dests]
        return [["{python}", "-c", _REGRESSION_RUNNER, "--names", ".", *argv[3:], "--", *hidden]]
    start = argv[argv.index("-s") + 1] if "-s" in argv else "."
    top = argv[argv.index("-t") + 1] if "-t" in argv else "."
    modules = [_safe_rel(i["dest"]).with_suffix("").as_posix().replace("/", ".") for i in task.hidden]
    return [["{python}", "-c", _REGRESSION_RUNNER, start, top, *modules]]


def install_hidden(task: Task, ws: Path) -> None:
    from .fsutil import UnsafePath, ensure_inside
    for item in task.hidden:
        src = task.dir / _safe_rel(item["src"])
        dst = ws / _safe_rel(item["dest"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            ensure_inside(ws, dst)  # the agent may have planted symlinks in the workspace
        except UnsafePath as exc:
            raise SuiteError(str(exc)) from exc
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.copyfile(src, dst)


def hidden_materials(task: Task) -> list[tuple[str, bytes]]:
    """(workspace destination, bytes) of each hidden test file."""
    return [(i["dest"], (task.dir / _safe_rel(i["src"])).read_bytes()) for i in task.hidden]


def contamination(task: Task, ws: Path) -> list[str]:
    """Workspace files byte-identical to a hidden test. Since 0.7.6 this is a
    diagnostic only (a correct fix can reproduce an upstream test exactly);
    the lab's verdict comes from `integrity.assess`, which needs proof of
    access."""
    hidden = {(task.dir / _safe_rel(i["src"])).read_bytes() for i in task.hidden}
    found = []
    for path in ws.rglob("*"):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size < 2_000_000 and path.read_bytes() in hidden:
                found.append(path.relative_to(ws).as_posix())
        except OSError:
            continue
    return found


def expand(argv: list[str], ws: Path, out: Path) -> list[str]:
    result: list[str] = []
    for token in argv:
        if token == "{python}":
            result.append(sys.executable)
        elif token == "{node}":
            result.append(shutil.which("node") or "node")
        elif token == "{out}":
            result.append(str(out))
        elif token.startswith("{glob:") and token.endswith("}"):
            pattern = token[len("{glob:"):-1]
            matches = sorted(p.relative_to(ws).as_posix() for p in ws.glob(pattern) if p.is_file())
            result.extend(matches)
        else:
            result.append(token.replace("{out}", str(out)))
    return result


@dataclass(slots=True)
class CommandResult:
    ok: bool
    steps: list[dict[str, Any]] = field(default_factory=list)


def run_commands(commands: list[list[str]], ws: Path, timeout: float) -> CommandResult:
    out = Path(tempfile.mkdtemp(prefix="repo-ai-eval-out-"))
    result = CommandResult(ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        for argv in commands:
            cmd = expand(argv, ws, out)
            started = time.monotonic()
            try:
                proc = subprocess.run(cmd, cwd=ws, capture_output=True, timeout=timeout,
                                      check=False, env=env)
                code = proc.returncode
            except FileNotFoundError:
                code = 127
            except subprocess.TimeoutExpired:
                code = 124
            result.steps.append({"cmd": PurePosixPath(argv[0]).name, "exit": code,
                                 "seconds": round(time.monotonic() - started, 2)})
            if code != 0:
                result.ok = False
                break
    finally:
        shutil.rmtree(out, ignore_errors=True)
    return result


def missing_toolchain(base: Base) -> list[str]:
    return [tool for tool in base.toolchain
            if tool != "python" and shutil.which(tool) is None]


# --------------------------------------------------------------------------
# offline: oracle validation
# --------------------------------------------------------------------------
def validate_task(task: Task, base: Base, suite: Path, work: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"id": task.id, "status": "valid", "problems": []}
    missing = missing_toolchain(base)
    if missing:
        row.update(status="skipped", problems=[f"toolchain missing: {', '.join(missing)}"])
        return row
    base_dir = suite / "bases" / task.base
    prompt = task.prompt.lower()
    rewritten = {e["file"] for e in task.setup}
    for item in task.hidden:
        dest = _safe_rel(item["dest"])
        # an existing file is allowed only when setup replaces it (a re-injected
        # bug: the visible test file is the pre-fix version, the hidden one the fix's)
        if (base_dir / dest).exists() and dest.as_posix() not in rewritten:
            row["problems"].append(f"hidden dest {dest} exists in the base")
        if dest.stem.lower() in prompt:
            row["problems"].append(f"prompt names hidden test {dest.stem}")
    if base.third_party:
        # third-party code never runs on the host: oracle checks go through the sandbox
        try:
            from .coding_lab import _grading_backend, _run_cmds, _toolchain
            backend = _grading_backend("auto", _toolchain(base), base)
        except Exception as exc:  # noqa: BLE001 - no sandbox means "not validated", not a crash
            row.update(status="skipped", problems=[f"third-party base needs a sandbox: {exc}"])
            return row

        def runs(commands: list[list[str]], ws: Path) -> bool:
            return bool(_run_cmds(backend, commands, ws, _toolchain(base), task.timeout_s * 2).ok)
    else:
        def runs(commands: list[list[str]], ws: Path) -> bool:
            return run_commands(commands, ws, task.timeout_s).ok
    try:
        start = materialize(task, suite, work / "start", git=False)
        if task.hidden and any((start / _safe_rel(i["dest"])).exists() and
                               (start / _safe_rel(i["dest"])).read_bytes() ==
                               (task.dir / _safe_rel(i["src"])).read_bytes() for i in task.hidden):
            row["problems"].append("the starting state already contains a hidden test")
        if base.third_party and not runs(base.visible_tests, start):
            row["problems"].append("visible tests fail on the starting state")
        install_hidden(task, start)
        if runs(task.commands, start):
            row["problems"].append("hidden tests pass on the starting state")
        solved = materialize(task, suite, work / "solved", solved=True, git=False)
        if task.visible_after_hidden:
            install_hidden(task, solved)
        if not runs(regression_commands(task, base), solved):
            row["problems"].append("visible tests fail after the reference solution")
        install_hidden(task, solved)
        if not runs(task.commands, solved):
            row["problems"].append("hidden tests fail on the reference solution")
        changed = {e["file"] for e in task.solution}
        if not set(task.gold_files) <= changed | {e["file"] for e in task.setup}:
            row["problems"].append("gold_files not touched by the solution")
    except (SuiteError, OSError, subprocess.SubprocessError) as exc:
        row["problems"].append(f"error: {exc}")
    if row["problems"]:
        row["status"] = "invalid"
    return row


# --------------------------------------------------------------------------
# offline: localization
# --------------------------------------------------------------------------
def _terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", text)
    out: list[str] = []
    for word in words:
        for part in re.split(r"_|(?<=[a-z])(?=[A-Z])", word):
            low = part.lower()
            if len(low) >= 3 and low not in _STOP:
                out.append(low)
    return list(dict.fromkeys(out))


def naive_rank(ws: Path, prompt: str) -> list[str]:
    """What plain grep gets you: files ranked by how many prompt terms they
    contain, ties broken by total hits (the baseline for localization)."""
    terms = _terms(prompt)
    scores: list[tuple[int, int, str]] = []
    for path in sorted(ws.rglob("*")):
        if not path.is_file() or ".git" in path.parts or ".repo-ai" in path.parts \
                or ".claude" in path.parts:
            continue
        try:
            text = path.read_text("utf-8", errors="ignore").lower()
        except OSError:
            continue
        rel = path.relative_to(ws).as_posix().lower()
        hits = [text.count(t) + 3 * rel.count(t) for t in terms]
        present = sum(1 for h in hits if h)
        if present:
            scores.append((-present, -sum(hits), path.relative_to(ws).as_posix()))
    return [rel for _, _, rel in sorted(scores)]


def rank_metrics(ranked: list[str], gold: list[str], k: int = 5) -> dict[str, Any]:
    positions = [ranked.index(g) + 1 for g in gold if g in ranked]
    first = min(positions) if positions else None
    return {
        "recall_at_k": round(sum(1 for p in positions if p <= k) / len(gold), 3) if gold else 0.0,
        "all_at_k": bool(gold) and len([p for p in positions if p <= k]) == len(gold),
        "mrr": round(1.0 / first, 3) if first else 0.0,
        "first_rank": first,
    }


def _cli(args: list[str], cwd: Path, stdin: str | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE_"))}
    full_env["REPO_AI_NO_BACKGROUND"] = "1"
    full_env.update(env or {})
    from .fsutil import self_argv
    return subprocess.run(self_argv(*args), cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", input=stdin, timeout=300, check=False,
                          env=full_env)


def localize(task: Task, suite: Path, work: Path, k: int = 5) -> dict[str, Any]:
    ws = materialize(task, suite, work / "loc")
    naive = rank_metrics(naive_rank(ws, task.prompt), task.gold_files, k)
    init = _cli(["init", "--agent", "claude", "--smart", "-q"], ws)
    if init.returncode != 0:
        return {"id": task.id, "error": "repo-ai init failed", "naive": naive}
    ctx = _cli(["context", task.prompt, "--format", "json"], ws)
    ranked: list[str] = []
    confidence = "none"
    try:
        data = json.loads(ctx.stdout)
        ranked = [f["path"] for f in data.get("results", [])]
        confidence = data.get("confidence", "none")
    except ValueError:
        pass
    hook = _cli(["hook", "claude", "prompt"], ws, stdin=json.dumps({"prompt": task.prompt}),
                env={"CLAUDE_PROJECT_DIR": str(ws)})
    injected = ""
    try:
        injected = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"] \
            if hook.stdout.strip() else ""
    except (ValueError, KeyError, TypeError):
        injected = ""
    return {
        "id": task.id, "category": task.category, "language": task.language,
        "repo_ai": rank_metrics(ranked, task.gold_files, k), "naive": naive,
        "confidence": confidence,
        "hook_injected": bool(injected),
        "hook_gold_in_payload": all(g in injected for g in task.gold_files) if injected else False,
        "hook_tokens_est": math.ceil(len(injected) / 4),
    }


def _mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 3) if values else 0.0


def summarize_localization(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if "repo_ai" in r]
    summary: dict[str, Any] = {"tasks": len(ok)}
    for arm in ("repo_ai", "naive"):
        summary[arm] = {
            "recall_at_5": _mean([r[arm]["recall_at_k"] for r in ok]),
            "all_gold_at_5": _mean([1.0 if r[arm]["all_at_k"] else 0.0 for r in ok]),
            "mrr": _mean([r[arm]["mrr"] for r in ok]),
        }
    summary["hook_injection_rate"] = _mean([1.0 if r["hook_injected"] else 0.0 for r in ok])
    summary["hook_payload_has_all_gold"] = _mean([1.0 if r["hook_gold_in_payload"] else 0.0
                                                  for r in ok])
    summary["hook_tokens_est_mean"] = _mean([r["hook_tokens_est"] for r in ok if r["hook_injected"]])
    summary["regressions_vs_naive"] = sorted(
        r["id"] for r in ok if r["repo_ai"]["mrr"] < r["naive"]["mrr"])
    return summary


def run_offline(suite: Path, tasks: list[Task], bases: dict[str, Base], *,
                validate: bool = True, localization: bool = True,
                concurrency: int = 1) -> dict[str, Any]:
    started = time.monotonic()
    report: dict[str, Any] = {"schema": SCHEMA_VERSION, "mode": "offline",
                              "suite": suite.name, "tasks": len(tasks)}

    def one(task: Task) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with tempfile.TemporaryDirectory(prefix=f"repo-ai-eval-{task.id[:24]}-") as tmp:
            work = Path(tmp)
            v = validate_task(task, bases[task.base], suite, work) if validate else None
            loc = localize(task, suite, work, 5) if localization else None
            return v, loc

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, tasks))
    if validate:
        rows = [v for v, _ in results if v]
        report["validation"] = {
            "valid": sum(1 for r in rows if r["status"] == "valid"),
            "invalid": [r for r in rows if r["status"] == "invalid"],
            "skipped": [r for r in rows if r["status"] == "skipped"],
        }
    if localization:
        locs = [loc for _, loc in results if loc]
        report["localization"] = {"summary": summarize_localization(locs), "tasks": locs}
    report["counts"] = {
        "by_language": _count(tasks, "language"), "by_category": _count(tasks, "category"),
        "by_base": _count(tasks, "base")}
    report["elapsed_s"] = round(time.monotonic() - started, 1)
    return report


def _count(tasks: list[Task], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        key = getattr(task, attr)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# live: headless Claude Code runs
# --------------------------------------------------------------------------
# Same permissions for both arms: file tools inside the workspace, the test
# runners the suite needs, read-only git, and repo-ai's read-only queries.
# Everything else (web tools, network clients, other shells) is denied
# without prompting under `dontAsk`.
ALLOWED_TOOLS = (
    "Read", "Edit", "Write", "MultiEdit", "Glob", "Grep", "TodoWrite", "Task",
    "Bash(python -m unittest:*)", "Bash(python3 -m unittest:*)", "Bash(python -m pytest:*)",
    "Bash(python3 -m pytest:*)", "Bash(pytest:*)", "Bash(node --test:*)", "Bash(npm test:*)",
    "Bash(javac:*)", "Bash(java -cp:*)", "Bash(make test:*)", "Bash(ls:*)",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
    "Bash(repo-ai context:*)", "Bash(repo-ai impact:*)", "Bash(repo-ai explain:*)",
    "Bash(repo-ai symbol:*)", "Bash(repo-ai related:*)", "Bash(repo-ai packet:*)",
    "Bash(repo-ai status:*)",
)
DISALLOWED_TOOLS = ("WebFetch", "WebSearch", "Bash(curl:*)", "Bash(wget:*)",
                    "Bash(git push:*)", "Bash(pip install:*)", "Bash(npm install:*)")


# Anthropic's price *ratios* are the same for every Claude model: cache writes
# (5-minute) cost 1.25x fresh input, cache reads 0.1x, output 5x. With the
# run's reported total cost they give each API call's cost without assuming
# absolute prices.
_PRICE_RATIO = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25,
                "cache_read_input_tokens": 0.1, "output_tokens": 5.0}


def _price_units(usage: dict[str, Any]) -> float:
    return sum(float(usage.get(k) or 0) * w for k, w in _PRICE_RATIO.items())


def _call_costs(calls: dict[str, float], cost: Any) -> dict[str, Any]:
    """Per-call cost estimate. Claude Code checks `--max-budget-usd` between
    API calls, so a run can overshoot its cap by at most one call: the largest
    call is what the per-run reservation margin has to cover."""
    total = sum(calls.values())
    out: dict[str, Any] = {"api_calls": len(calls)}
    if calls and total > 0 and isinstance(cost, (int, float)):
        out["max_call_cost_usd_est"] = round(float(cost) * max(calls.values()) / total, 4)
    return out


def _token_accounting(usage: dict[str, Any], model_usage: Any) -> dict[str, Any]:
    """Token counts, the same way for every arm. `modelUsage` (per model, all
    of a session's models, subagents included) is preferred; the top-level
    `usage` describes the main model only. Cache reads and creation are kept
    separate from fresh input: they are billed very differently."""
    if isinstance(model_usage, dict) and model_usage:
        def total(key: str) -> int:
            return sum(int((m or {}).get(key) or 0) for m in model_usage.values() if isinstance(m, dict))
        fresh, read = total("inputTokens"), total("cacheReadInputTokens")
        created, out = total("cacheCreationInputTokens"), total("outputTokens")
        return {"input_tokens": fresh + read + created, "output_tokens": out,
                "uncached_input_tokens": fresh, "cache_read_tokens": read, "cache_creation_tokens": created,
                "token_source": "modelUsage", "models_used": sorted(str(k) for k in model_usage),
                "main_model_input_tokens": sum(int(usage.get(k) or 0) for k in
                                               ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens")) if usage else None}
    if not usage:
        return {"input_tokens": None, "output_tokens": None, "uncached_input_tokens": None,
                "cache_read_tokens": None, "cache_creation_tokens": None, "token_source": None}
    fresh = int(usage.get("input_tokens") or 0)
    read = int(usage.get("cache_read_input_tokens") or 0)
    created = int(usage.get("cache_creation_input_tokens") or 0)
    return {"input_tokens": fresh + read + created, "output_tokens": int(usage.get("output_tokens") or 0),
            "uncached_input_tokens": fresh, "cache_read_tokens": read, "cache_creation_tokens": created,
            "token_source": "usage"}


def parse_stream(lines: list[str], ws: Path, gold: list[str]) -> dict[str, Any]:
    """Reduce a stream-json transcript to metrics. Unknown events are ignored,
    so newer Claude Code versions degrade to fewer metrics, not errors."""
    tools: dict[str, int] = {}
    reads_before_edit: list[str] = []
    first_edit: str | None = None
    result: dict[str, Any] = {}
    hook_events = 0
    model = None
    skills_invoked: list[str] = []
    calls: dict[str, float] = {}  # API call (message id) -> price-weighted token units
    bash_commands: list[str] = []  # what the agent ran, so behaviour differences are auditable

    def rel(raw: Any) -> str:
        if not isinstance(raw, str):
            return ""
        try:
            return Path(raw).resolve().relative_to(ws.resolve()).as_posix()
        except ValueError:
            return raw

    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "system":
            if event.get("subtype") == "init":
                model = event.get("model")
            elif str(event.get("subtype", "")).startswith("hook_"):
                hook_events += 1
        elif kind == "assistant":
            message = event.get("message") or {}
            usage_now = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage_now, dict):
                key = str(message.get("id") or f"call-{len(calls)}")
                calls[key] = max(calls.get(key, 0.0), _price_units(usage_now))
            content = (event.get("message") or {}).get("content") or []
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", ""))
                tools[name] = tools.get(name, 0) + 1
                raw_input = block.get("input")
                tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
                if name == "Bash" and isinstance(tool_input.get("command"), str) \
                        and len(bash_commands) < MAX_BASH_RECORDED:
                    bash_commands.append(tool_input["command"][:BASH_COMMAND_CHARS])
                if name == "Skill":
                    sk = next((v for k in ("skill", "name", "command")
                               if isinstance(v := tool_input.get(k), str)), "")
                    if sk.strip():
                        skills_invoked.append(sk.strip().lstrip("/").split()[0][:64])
                path = rel(tool_input.get("file_path") or tool_input.get("notebook_path"))
                if name in EDIT_TOOLS and first_edit is None:
                    first_edit = path
                elif name in READ_TOOLS and first_edit is None and path \
                        and path not in reads_before_edit:
                    reads_before_edit.append(path)
        elif kind == "result":
            result = event
    raw_usage = result.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    cost = result.get("total_cost_usd")
    return {
        "model": model,
        "subtype": result.get("subtype"),
        "is_error": bool(result.get("is_error", not result)),
        "turns": result.get("num_turns"),
        "duration_s": round(result["duration_ms"] / 1000, 1)
        if isinstance(result.get("duration_ms"), (int, float)) else None,
        "reported_cost_usd": round(float(cost), 4) if isinstance(cost, (int, float)) else None,
        **_token_accounting(usage, result.get("modelUsage")),
        **_call_costs(calls, cost),
        "tool_uses": dict(sorted(tools.items())),
        "subagent_calls": sum(tools.get(n, 0) for n in SUBAGENT_TOOLS),
        "bash_commands": bash_commands,
        "test_commands": sum(1 for c in bash_commands if TEST_COMMAND.search(c)),
        "files_read_before_first_edit": len(reads_before_edit),
        "first_edit": first_edit,
        "first_edit_in_gold": first_edit in gold if first_edit else None,
        "hook_events": hook_events,
        "skills_invoked": skills_invoked,
    }


# What a headless agent run inherits from the host: enough to run Claude
# Code and the toolchains, nothing that carries a credential (GITHUB_TOKEN,
# AWS_*, SSH_AUTH_SOCK, ...). Untrusted task text could make the model print
# anything it can see.
AGENT_ENV_KEYS = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR",
                            "TZ", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
                            "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
                            "JAVA_HOME", "SYSTEMROOT", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA",
                            "USERPROFILE"})


def agent_env(extra: dict[str, str] | None = None, allow_api_key: bool = True) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in AGENT_ENV_KEYS or k.startswith("LC_")}
    if allow_api_key and os.environ.get("REPO_AI_LAB_USE_API_KEY") == "1" and os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]  # explicit opt-in only
    env.update(extra or {})
    return env


def _flight_tokens(ws: Path) -> int:
    path = ws / ".repo-ai" / "state" / "flight.jsonl"
    total = 0
    try:
        for line in path.read_text("utf-8").splitlines():
            try:
                total += int(json.loads(line).get("tokens_est", 0))
            except (ValueError, AttributeError):
                continue
    except OSError:
        return 0
    return total


def render_offline(report: dict[str, Any]) -> str:
    lines = [f"repo-ai eval (offline) — {report['tasks']} tasks, {report['elapsed_s']} s"]
    v = report.get("validation")
    if v:
        lines.append(f"  oracle validation: {v['valid']} valid, {len(v['invalid'])} invalid, "
                     f"{len(v['skipped'])} skipped")
        for row in v["invalid"]:
            lines.append(f"    INVALID {row['id']}: {'; '.join(row['problems'])}")
        for row in v["skipped"]:
            lines.append(f"    skipped {row['id']}: {'; '.join(row['problems'])}")
    loc = report.get("localization")
    if loc:
        s = loc["summary"]
        lines.append(f"  localization from the prompt alone ({s['tasks']} tasks):")
        lines.append("                     recall@5  all-gold@5   MRR")
        for arm, label in (("repo_ai", "repo-ai"), ("naive", "naive grep")):
            a = s[arm]
            lines.append(f"    {label:14s}  {a['recall_at_5']:8.3f}  {a['all_gold_at_5']:10.3f}  "
                         f"{a['mrr']:5.3f}")
        lines.append(f"  prompt hook: injects on {s['hook_injection_rate']:.0%} of tasks, "
                     f"payload holds every gold file on {s['hook_payload_has_all_gold']:.0%}, "
                     f"~{s['hook_tokens_est_mean']:.0f} tokens (estimate) when it injects")
        if s["regressions_vs_naive"]:
            lines.append(f"  worse than naive grep on: {', '.join(s['regressions_vs_naive'])}")
    lines.append("  task success with Claude: not measured offline (use --live with a budget)")
    return "\n".join(lines)


def to_json(report: dict[str, Any]) -> str:
    def default(obj: Any) -> Any:
        if isinstance(obj, Path):
            return obj.as_posix()
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        raise TypeError(type(obj).__name__)
    return json.dumps(report, indent=2, default=default) + "\n"


def compare_offline(now: dict[str, Any], baseline: dict[str, Any],
                    tolerance: float = 0.02) -> list[str]:
    """Promotion gate: problems when the current offline run is worse."""
    problems: list[str] = []
    v_now, v_base = now.get("validation", {}), baseline.get("validation", {})
    if v_now and v_now.get("invalid"):
        problems.append(f"{len(v_now['invalid'])} invalid tasks")
    if v_now and v_base and v_now.get("valid", 0) < v_base.get("valid", 0):
        problems.append("fewer valid tasks than the baseline")
    s_now = now.get("localization", {}).get("summary", {})
    s_base = baseline.get("localization", {}).get("summary", {})
    for key in ("recall_at_5", "mrr", "all_gold_at_5"):
        a = s_now.get("repo_ai", {}).get(key)
        b = s_base.get("repo_ai", {}).get(key)
        if a is not None and b is not None and a < b - tolerance:
            problems.append(f"localization {key} regressed {b} -> {a}")
    return problems
