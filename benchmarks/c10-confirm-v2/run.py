"""c10-confirm-v2 harness (PREREGISTRATION.md). Designed 2026-11-06; NOT RUN.

    python run.py check [--strict] [--selftest]   # offline, no model call (the only stage run at design time)
    python run.py probe   --work DIR               # $0: Claude Code init with a model name that does not exist, no token
    python run.py prepare --work DIR --repo-ai EXE
    python run.py run     --work DIR --token-file ~/.config/repo-ai/claude-token
    python run.py grade   --work DIR [--export]

check: validates the materials layout (PENDING items are not errors unless --strict; --strict is the freeze gate:
visible tests pass, REVIEW deletions applied, no oracle assertion passes on the untouched fixture). --selftest also
exercises prepare (all three arms) and grading offline on a temporary copy, using c10-confirm-v1's frozen materials
as a stand-in, and expects 0 passing oracle assertions on the untouched projects.
probe: records Claude Code's built-in skills and plugins for the installed version (v1 Amendment 1 method), plus
whether a project CLAUDE.md shows up in the init event. No token is passed, so no model can be invoked.
prepare: one project per run (fixture copy, git, `repo-ai init --agent none`, then the arm: skill installed with
`repo-ai skills install`, or the SKILL.md body as CLAUDE.md, or nothing), order shuffled with a recorded seed.
run: `claude -p` per run, model claude-haiku-5-5, a new empty CLAUDE_CONFIG_DIR per run, token from --token-file
(token_env; never printed or recorded). Hard caps: 72 billed sessions, $0.05 per session, $3.60 for the study.
grade: oracle per run in a network-denied sandbox, in run-id order, arms looked up afterwards; validity from each
run's init event; primary (skill vs control), secondary (skill vs claudemd) and tertiary (claudemd vs control).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1 = HERE.parent / "c10-confirm-v1"
MODEL = "claude-haiku-5-5"  # full name, not the alias: the init event must report exactly this model
ARMS = ("skill", "claudemd", "control")
REPEATS = 3
N_TASKS = 8
MIN_TASKS = 6  # a task left with no convention assertion after the review is dropped (reported)
RUN_CAP_USD = 0.05  # Claude Code --max-budget-usd per session
BUDGET_USD = 3.60  # study ceiling: a session is not started if it could take the spend above it
MAX_SESSIONS = 72  # billed sessions (reached the model); never more, whatever happens
MAX_ZERO_STARTS = 3  # starts that ended before any model turn at $0 (e.g. authentication_failed); each stops the stage
TOOLS = "Read,Write,Edit,Glob,Grep,Skill"
PROBE_MODEL = "repo-ai-isolation-probe-not-a-model"
RULES_MIN, RULES_MAX = 10, 14
_DROP = {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN"}
CLEAN = {k: v for k, v in os.environ.items() if k not in _DROP and not k.startswith("ANTHROPIC_")}


# ---------------------------------------------------------------- materials

def _skill_dir(root: Path) -> Path:
    dirs = [d for d in (root / "skill").iterdir() if d.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def _tasks(root: Path) -> list[dict]:
    return json.loads((root / "tasks.json").read_text())["tasks"]


def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def claudemd_text(root: Path) -> str:
    """The CLAUDE.md of the claudemd arm: the SKILL.md body after its frontmatter, verbatim (leading blank lines
    dropped). Same rules, same words, delivered as always-loaded project memory instead of an installed skill."""
    _, body = _split_frontmatter((_skill_dir(root) / "SKILL.md").read_text())
    return body.lstrip("\n")


def _rule_numbers(body: str) -> list[int]:
    return [int(n) for n in re.findall(r"^(\d+)\.\s", body, re.M)]


# ---------------------------------------------------------------- shell helpers

def sh(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env or CLEAN, capture_output=True, text=True, check=True)


def _git(proj: Path, *args: str) -> str:
    return sh(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
               "-c", "commit.gpgsign=false", *args], proj).stdout


def _work(path: Path) -> Path:
    """The work directory: under HOME, and no path component starting with '-'. v1 ran under a directory named
    '-Users-...', and three control runs then read a mangled path and never edited (v1 RESULTS.md, Disclosed)."""
    work = path.expanduser().resolve()
    if Path.home().resolve() not in work.parents:
        raise SystemExit("--work must be under HOME")
    if any(part.startswith("-") for part in work.parts):
        raise SystemExit("--work must not contain a path component starting with '-'")
    return work


def _claude_version() -> str:
    out = subprocess.run(["claude", "--version"], capture_output=True, text=True, env=CLEAN).stdout
    m = re.search(r"\d+\.\d+\.\d+", out)
    assert m, out
    return m.group(0)


def _probe_path(version: str) -> Path:
    return HERE / "probe" / f"builtin-init-{version}.json"


# ---------------------------------------------------------------- check (offline)

class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, item: str, detail: str = "") -> None:
        self.rows.append((status, item, detail))

    def has(self, *statuses: str) -> bool:
        return any(s in statuses for s, _, _ in self.rows)

    def print(self) -> None:
        for s, item, detail in self.rows:
            print(f"{s:8} {item}" + (f": {detail}" if detail else ""))


def _grade_profile(proj: Path, tmp: Path) -> str:
    q = json.dumps
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            f"(allow file-write* (subpath {q(str(proj))}))(allow file-write* (subpath {q(str(tmp))}))"
            '(allow file-write* (literal "/dev/null"))')


def _pytest_sandboxed(proj: Path, args: list[str]) -> subprocess.CompletedProcess:
    tmp = Path(tempfile.mkdtemp(prefix="c10v2grade-"))
    env = dict(CLEAN, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(tmp))
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=no", "-rA", *args]
    if sys.platform == "darwin":
        cmd = ["/usr/bin/sandbox-exec", "-p", _grade_profile(proj.resolve(), tmp.resolve()), *cmd]
    try:
        return subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True, timeout=300)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def grade_one(root: Path, proj: Path, task_id: str) -> dict:
    target = proj / f"test_oracle_{task_id}.py"
    shutil.copyfile(root / "oracle" / f"test_{task_id}.py", target)
    try:
        p = _pytest_sandboxed(proj, [target.name])
    finally:
        target.unlink(missing_ok=True)
    passed = {line.split("::", 1)[1].split()[0] for line in p.stdout.splitlines()
              if line.startswith("PASSED ") and "::" in line}
    return {"passed": sorted(passed), "tail": p.stdout[-300:]}


def _review_marks(text: str) -> tuple[set, set, set]:
    keep, delete, leak = set(), set(), set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3 and cells[0] == "LEAK":
            leak.add(cells[1])
        elif len(cells) >= 2 and cells[0].startswith("test_") and cells[1] in ("KEEP", "DELETE"):
            (keep if cells[1] == "KEEP" else delete).add(cells[0])
    return keep, delete, leak


def check(root: Path, strict: bool, cli_required: bool = True) -> Report:
    rep = Report()
    pend = "ERROR" if strict else "PENDING"

    # Author A: fixture
    fx = root / "fixture"
    pkg = None
    if not fx.is_dir():
        rep.add(pend, "fixture/", "to be written by Author A")
    else:
        pkgs = [d for d in fx.iterdir() if d.is_dir() and (d / "__init__.py").is_file() and d.name != "tests"]
        if not (fx / "pyproject.toml").is_file() or not (fx / "tests").is_dir() or len(pkgs) != 1:
            rep.add("ERROR", "fixture/", "needs pyproject.toml, tests/ and exactly one package")
        else:
            pkg = pkgs[0]
            rep.add("OK", "fixture/", f"package {pkg.name}")
            if cli_required:
                cli = pkg / "cli.py"
                ok = cli.is_file() and re.search(r"^def main\(", cli.read_text(), re.M) and (pkg / "__main__.py").is_file()
                rep.add("OK" if ok else "ERROR", "fixture CLI entry point",
                        f"{pkg.name}/cli.py main(argv) and {pkg.name}/__main__.py" + ("" if ok else " missing"))
            work = Path(tempfile.mkdtemp(prefix="c10v2fx-"))
            try:
                shutil.copytree(fx, work / "p")
                p = _pytest_sandboxed(work / "p", [])
                last = (p.stdout.strip().splitlines() or [""])[-1]
                rep.add("OK" if p.returncode == 0 else "ERROR", "visible tests pass", last)
            finally:
                shutil.rmtree(work, ignore_errors=True)

    # Author A: skill and notes
    rules: list[int] = []
    skill_name = None
    if not (root / "skill").is_dir():
        rep.add(pend, "skill/<name>/SKILL.md", "to be written by Author A")
    else:
        try:
            sd = _skill_dir(root)
            meta, body = _split_frontmatter((sd / "SKILL.md").read_text())
            skill_name = sd.name
            rules = _rule_numbers(body)
            problems = []
            if meta.get("name") != sd.name:
                problems.append("frontmatter name must equal the directory name")
            if not meta.get("description"):
                problems.append("frontmatter description missing")
            if not (sd / "LICENSE").is_file():
                problems.append("LICENSE missing")
            if rules != list(range(1, len(rules) + 1)) or not RULES_MIN <= len(rules) <= RULES_MAX:
                problems.append(f"rules must be numbered 1..N with {RULES_MIN} <= N <= {RULES_MAX}, found {rules}")
            rep.add("ERROR" if problems else "OK", f"skill/{sd.name}", "; ".join(problems) or f"{len(rules)} rules")
        except (AssertionError, OSError) as exc:
            rep.add("ERROR", "skill/", str(exc))
    rep.add("OK" if (root / "A_NOTES.md").is_file() else pend, "A_NOTES.md", "inferability table by Author A")

    # Author B: tasks and oracles
    tasks = None
    if not (root / "tasks.json").is_file():
        rep.add(pend, "tasks.json", "to be written by Author B")
        if not (root / "oracle").is_dir():
            rep.add(pend, "oracle/", "to be written by Author B")
    else:
        problems = []
        try:
            tasks = _tasks(root)
        except (ValueError, KeyError) as exc:
            problems.append(f"unreadable: {exc}")
            tasks = []
        ids = [t.get("id") for t in tasks]
        allowed_ids = [f"t{i}" for i in range(1, N_TASKS + 1)]
        if ids != [i for i in allowed_ids if i in ids] or len(ids) < MIN_TASKS:
            problems.append(f"ids must be t1..t{N_TASKS} in order (a task dropped by the review may be missing; "
                            f"at least {MIN_TASKS} kept), found {ids}")
        names: list[str] = []
        for t in tasks:
            req = str(t.get("request", ""))
            banned = [w for w in ("skill", "convention", "claude.md", *([skill_name] if skill_name else []))
                      if w and w.lower() in req.lower()]
            if not req.strip() or banned:
                problems.append(f"{t.get('id')}: request empty or names {banned}")
            kinds = [a.get("kind") for a in t.get("assertions", [])]
            if "convention" not in kinds or set(kinds) - {"baseline", "convention"}:
                problems.append(f"{t.get('id')}: needs >= 1 convention assertion (kinds: baseline, convention)")
            for a in t.get("assertions", []):
                names.append(a.get("test", ""))
                if not re.fullmatch(rf"test_{t.get('id')}_{a.get('kind')}_\w+", a.get("test", "")):
                    problems.append(f"{a.get('test')}: name must be test_<id>_<kind>_<slug>")
                if a.get("kind") == "convention" and not (isinstance(a.get("rule"), int) and
                                                          (not rules or 1 <= a["rule"] <= len(rules))):
                    problems.append(f"{a.get('test')}: convention assertion must cite one rule number")
                if a.get("kind") == "baseline" and a.get("rule") is not None:
                    problems.append(f"{a.get('test')}: baseline assertion cites no rule")
        if len(names) != len(set(names)):
            problems.append("duplicate test names")
        n_conv = sum(a.get("kind") == "convention" for t in tasks for a in t.get("assertions", []))
        dropped = [i for i in [f"t{k}" for k in range(1, N_TASKS + 1)] if i not in ids]
        rep.add("ERROR" if problems else "OK", "tasks.json",
                "; ".join(problems[:6]) or f"{len(tasks)} tasks, {len(names)} assertions ({n_conv} convention)"
                + (f"; dropped: {dropped}" if dropped else ""))
        if not (root / "oracle").is_dir():
            rep.add(pend, "oracle/", "to be written by Author B")
        else:
            bad = []
            for t in tasks:
                f = root / "oracle" / f"test_{t['id']}.py"
                if not f.is_file():
                    bad.append(f"{f.name} missing")
                    continue
                defined = {n.name for n in ast.walk(ast.parse(f.read_text()))
                           if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}
                listed = {a["test"] for a in t.get("assertions", [])}
                if defined != listed:
                    bad.append(f"{f.name}: defined {sorted(defined ^ listed)} differ from tasks.json")
            rep.add("ERROR" if bad else "OK", "oracle/", "; ".join(bad[:6]) or "one file per task, names match")

    # Reviewer C
    if not (root / "REVIEW.md").is_file():
        rep.add(pend, "REVIEW.md", "to be written by Reviewer C")
    elif tasks is not None:
        keep, delete, leak = _review_marks((root / "REVIEW.md").read_text())
        listed = {a["test"] for t in tasks for a in t.get("assertions", [])}
        problems = []
        if (delete | leak) & listed:
            problems.append(f"marked DELETE/LEAK but still present: {sorted((delete | leak) & listed)}")
        if listed - keep:
            problems.append(f"present but not marked KEEP: {sorted(listed - keep)}")
        rep.add("ERROR" if problems else "OK", "REVIEW.md applied",
                "; ".join(problems) or f"{len(keep)} KEEP, {len(delete)} DELETE, {len(leak)} LEAK")

    # Freeze gate: no oracle assertion passes on the untouched fixture
    if pkg is not None and tasks and (root / "oracle").is_dir():
        work = Path(tempfile.mkdtemp(prefix="c10v2fx-"))
        try:
            shutil.copytree(fx, work / "p")
            passing = [n for t in tasks if (root / "oracle" / f"test_{t['id']}.py").is_file()
                       for n in grade_one(root, work / "p", t["id"])["passed"]]
            rep.add("ERROR" if passing else "OK", "untouched fixture passes no oracle assertion",
                    ", ".join(passing) or "0 passing")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # Before the run (not a material): the built-in set for the installed Claude Code
    try:
        v = _claude_version()
        rep.add("OK" if _probe_path(v).is_file() else "PENDING", f"probe/builtin-init-{v}.json",
                "" if _probe_path(v).is_file() else "run `run.py probe` and commit it before any live run")
    except (OSError, AssertionError) as exc:
        rep.add("PENDING", "probe", f"claude not found: {exc}")
    return rep


def selftest() -> int:
    """Offline: prepare (all arms) and grade on untouched projects, with v1's frozen materials as a stand-in."""
    exe = shutil.which(os.environ.get("REPO_AI", "repo-ai"))
    if not exe:
        print("selftest: repo-ai not found")
        return 1
    rep = check(V1, strict=True, cli_required=False)
    rep.rows = [r for r in rep.rows if not r[1].startswith("probe")]  # the probe concerns live runs only
    print("-- v1 materials through the strict check (A_NOTES/REVIEW formats are v1's) --")
    rep.print()
    tmp = Path(tempfile.mkdtemp(prefix="c10v2self-"))
    try:
        runs = [{"task": t, "arm": arm, "repeat": 0, "id": f"{t}-{arm}"} for t in ("t1", "t4") for arm in ARMS]
        _prepare_runs(V1, tmp, runs, exe)
        bad = []
        for r in runs:
            g = grade_one(V1, tmp / r["id"] / "p", r["task"])
            if g["passed"]:
                bad.append(f"{r['id']} passed {g['passed']}")
        print("-- selftest: prepare (3 arms x 2 tasks) and sandboxed grading on untouched projects --")
        print("FAIL" if bad else "OK", "; ".join(bad) or f"{len(runs)} projects prepared, arm states asserted, "
                                                       "0 oracle assertions passing")
        # positive control: a v1 candidate that scored every assertion must score every assertion here too
        pos = []
        for cand, task in (("18e92d57", "t1"), ("113ec3aa", "t4")):
            proj = tmp / f"{task}-control" / "p"
            subprocess.run(["git", "apply", str(V1 / "results" / "candidates" / f"{cand}.diff")], cwd=proj,
                           check=True, capture_output=True)
            want = {a["test"] for t in _tasks(V1) if t["id"] == task for a in t["assertions"]}
            got = set(grade_one(V1, proj, task)["passed"])
            if got != want:
                pos.append(f"{cand} ({task}): missing {sorted(want - got)}")
        print("-- selftest: positive control (v1 full-score diffs re-applied and re-graded) --")
        print("FAIL" if pos else "OK", "; ".join(pos) or "18e92d57 (t1) 4/4, 113ec3aa (t4) 4/4")
        return 1 if bad or pos or rep.has("ERROR") else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- probe ($0, no token)

def _init_event(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            return ev
    return None


def probe(work: Path) -> None:
    version = _claude_version()
    out = _probe_path(version)
    assert not out.exists(), f"{out} exists"
    events = {}
    for name, claudemd in (("plain", False), ("claudemd", True)):
        proj = work / f"probe-{name}"
        proj.mkdir(parents=True)
        if claudemd:
            (proj / "CLAUDE.md").write_text("# probe\n\nThis file only checks whether project memory is listed.\n")
        cfg = Path(tempfile.mkdtemp(prefix="c10v2cfg-"))
        env = dict(CLEAN, CLAUDE_CONFIG_DIR=str(cfg))  # CLEAN carries no token: no model can be invoked
        cmd = ["claude", "-p", "probe", "--model", PROBE_MODEL, "--tools", TOOLS, "--setting-sources", "project",
               "--strict-mcp-config", "--permission-mode", "acceptEdits", "--no-session-persistence",
               "--output-format", "stream-json", "--verbose", "--max-budget-usd", "0.01"]
        p = subprocess.run(cmd, cwd=proj, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=120)
        shutil.rmtree(cfg, ignore_errors=True)
        ev = _init_event(p.stdout)
        assert ev, p.stdout[-500:] + p.stderr[-500:]
        events[name] = {k: v for k, v in ev.items() if k not in ("session_id", "uuid", "cwd")}
    base = events["plain"]
    differs = {k: events["claudemd"].get(k) for k in sorted(set(base) | set(events["claudemd"]))
               if base.get(k) != events["claudemd"].get(k)}
    record = {k: base.get(k) for k in ("tools", "mcp_servers", "skills", "plugins", "model", "apiKeySource",
                                       "claude_code_version")}
    record["init_keys"] = sorted(base)
    record["claudemd_project_differs"] = differs
    record["claudemd_project_plain_values"] = {k: base.get(k) for k in differs}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n")
    print("wrote", out, "| fields that differ with a project CLAUDE.md:", sorted(differs) or "none")


# ---------------------------------------------------------------- prepare

def _prepare_runs(root: Path, work: Path, runs: list[dict], exe: str) -> str:
    skill = _skill_dir(root)
    memory = claudemd_text(root)
    approve = ""
    for r in runs:
        proj = work / r["id"] / "p"
        shutil.copytree(root / "fixture", proj)
        env = dict(CLEAN, REPO_AI_HOME=str(work / r["id"] / "home"), REPO_AI_NO_BACKGROUND="1")
        _git(proj, "init", "-q", "-b", "main")
        _git(proj, "add", "-A")
        _git(proj, "commit", "-qm", "base")
        sh([exe, "init", "--agent", "none", "-q"], proj, env)
        for p in ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude"):
            assert not (proj / p).exists(), f"repo-ai init wrote {p}: the arms would no longer differ only as planned"
        if r["arm"] == "skill":
            out = sh([exe, "skills", "discover", "--from-path", str(skill), "--json"], proj, env).stdout
            data = json.loads(out)
            reports = data.get("reports") if isinstance(data.get("reports"), dict) else {}
            hashes = {x.get("content_hash") for x in reports.values() if isinstance(x, dict) and x.get("content_hash")}
            assert len(hashes) == 1, out[:400]
            approve = next(iter(hashes))
            sh([exe, "skills", "install", skill.name, "--approve", approve[:16], "--host", "claude-code"], proj, env)
        elif r["arm"] == "claudemd":
            (proj / "CLAUDE.md").write_text(memory)
        has_skill = (proj / ".claude" / "skills" / skill.name / "SKILL.md").is_file()
        has_memory = (proj / "CLAUDE.md").is_file()
        assert (has_skill, has_memory) == {"skill": (True, False), "claudemd": (False, True),
                                           "control": (False, False)}[r["arm"]], (r, has_skill, has_memory)
        if has_memory:
            assert (proj / "CLAUDE.md").read_text() == memory
        _git(proj, "add", "-A")
        _git(proj, "commit", "-qm", "arm setup", "--allow-empty")
        r["setup"] = _git(proj, "rev-parse", "HEAD").strip()
    return approve


def prepare(work: Path, exe: str) -> None:
    mapping = work / "mapping.json"
    assert not mapping.exists(), "already prepared"
    rep = check(HERE, strict=True)
    rep.rows = [r for r in rep.rows if not r[1].startswith("probe")]
    if rep.has("ERROR", "PENDING"):
        rep.print()
        raise SystemExit("materials are not frozen (check --strict fails)")
    work.mkdir(parents=True, exist_ok=True)
    seed = secrets.randbits(32)
    runs = [{"task": t["id"], "arm": arm, "repeat": k} for t in _tasks(HERE) for arm in ARMS for k in range(REPEATS)]
    assert len(runs) <= MAX_SESSIONS, len(runs)
    random.Random(seed).shuffle(runs)
    for r in runs:
        r["id"] = secrets.token_hex(4)
    approve = _prepare_runs(HERE, work, runs, exe)
    versions = {"repo_ai": sh([exe, "--version"], work).stdout.strip(), "claude_code": _claude_version(),
                "python": sys.version.split()[0]}
    mapping.write_text(json.dumps({"seed": seed, "skill": _skill_dir(HERE).name, "approve": approve, "model": MODEL,
                                   "versions": versions, "runs": runs}, indent=1))
    print("prepared", len(runs), "runs, seed", seed, versions)


# ---------------------------------------------------------------- run (live; not executed at design time)

def _read_token(path: Path) -> str:
    st = path.stat()
    if st.st_mode & 0o077:
        raise SystemExit("--token-file must not be readable by group or others (chmod 600)")
    token = path.read_text().strip()
    if not token or "\n" in token:
        raise SystemExit("--token-file must hold one token on one line")
    return token


def _stream_facts(path: Path) -> dict:
    facts = {"cost": 0.0, "assistant": 0, "model": None, "result": None}
    if not path.is_file():
        return facts
    for line in path.read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            facts["model"] = ev.get("model")
        elif ev.get("type") == "assistant":
            facts["assistant"] += 1
        elif ev.get("type") == "result":
            facts["result"] = ev.get("subtype")
            if isinstance(ev.get("total_cost_usd"), (int, float)):
                facts["cost"] = float(ev["total_cost_usd"])
    return facts


def _spent_and_billed(work: Path, runs: list[dict]) -> tuple[float, int]:
    spent, billed = 0.0, 0
    for r in runs:
        d = work / r["id"]
        if not (d / "started").exists():
            continue
        billed += 1
        f = _stream_facts(d / "stream.jsonl")
        # a started session with no reported cost (crash, kill) is counted at its full cap
        spent += f["cost"] if (d / "stream.jsonl").exists() and f["result"] else RUN_CAP_USD
    return spent, billed


def run(work: Path, token: str) -> None:
    m = json.loads((work / "mapping.json").read_text())
    assert m["model"] == MODEL
    version = _claude_version()
    if version != m["versions"]["claude_code"] or not _probe_path(version).is_file():
        raise SystemExit(f"Claude Code {version}: needs the version prepared with and a committed probe file")
    if (work / "ABORTED").exists():
        raise SystemExit("aborted earlier: " + (work / "ABORTED").read_text())
    zero_log = work / "zero_starts.jsonl"
    tasks = {t["id"]: t for t in _tasks(HERE)}
    for r in m["runs"]:
        d = work / r["id"]
        if (d / "started").exists():
            continue  # a session that started is never started again
        spent, billed = _spent_and_billed(work, m["runs"])
        zero = len(zero_log.read_text().splitlines()) if zero_log.exists() else 0
        if billed >= MAX_SESSIONS:
            print(f"session cap: {billed} sessions", flush=True)
            return
        if spent + RUN_CAP_USD > BUDGET_USD + 1e-9:
            print(f"budget stop: ${spent:.4f} spent; another session could exceed ${BUDGET_USD:.2f}", flush=True)
            return
        if zero >= MAX_ZERO_STARTS:
            print(f"stopped: {zero} starts ended before any model turn", flush=True)
            return
        (d / "started").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        cfg = Path(tempfile.mkdtemp(prefix="c10v2cfg-"))  # new and empty for every run
        env = dict(CLEAN, CLAUDE_CONFIG_DIR=str(cfg), CLAUDE_CODE_OAUTH_TOKEN=token)
        cmd = ["claude", "-p", tasks[r["task"]]["request"], "--model", MODEL, "--tools", TOOLS,
               "--setting-sources", "project", "--strict-mcp-config", "--permission-mode", "acceptEdits",
               "--no-session-persistence", "--output-format", "stream-json", "--verbose",
               "--max-budget-usd", f"{RUN_CAP_USD:.2f}"]
        try:
            p = subprocess.run(cmd, cwd=d / "p", env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=900)
            stdout, stderr, code = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr, code = "timeout after 900 s", "timeout"
        finally:
            shutil.rmtree(cfg, ignore_errors=True)
        stdout, stderr = stdout.replace(token, "<token>"), stderr.replace(token, "<token>")
        (d / "stream.jsonl").write_text(stdout)
        (d / "stderr.txt").write_text(stderr[-4000:])
        f = _stream_facts(d / "stream.jsonl")
        if f["assistant"] == 0 and f["cost"] == 0.0:
            # never reached the model: not billed, may be retried after the cause is fixed; stop now
            with zero_log.open("a") as fh:
                fh.write(json.dumps({"id": r["id"], "result": f["result"], "exit": code,
                                     "stderr_tail": stderr[-300:]}) + "\n")
            keep = d / f"zero-start-{zero + 1}"
            keep.mkdir()
            for name in ("started", "stream.jsonl", "stderr.txt"):
                (d / name).rename(keep / name)
            print(r["id"], "ended before any model turn; stage stopped", f["result"], flush=True)
            return
        if f["model"] != MODEL:
            (work / "ABORTED").write_text(f"run {r['id']}: init model {f['model']!r}, expected {MODEL!r}\n")
            print("ABORTED: model mismatch", f["model"], flush=True)
            return
        print(r["id"], "exit", code, f"${f['cost']:.4f}", flush=True)


# ---------------------------------------------------------------- grade

def audit(work: Path, rid: str, skill: str, arm: str, builtin: dict) -> dict:
    proj = str((work / rid / "p").resolve())
    tools, skill_calls, outside, cost, result, init, invalid = [], [], [], None, None, None, []
    stream = work / rid / "stream.jsonl"
    for line in (stream.read_text().splitlines() if stream.is_file() else []):
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
                    if c["name"] == "Skill":
                        skill_calls.append(inp.get("skill") or inp.get("command") or inp.get("name"))
                    for key in ("file_path", "path"):
                        v = inp.get(key)
                        if v and not str(Path(proj, v).resolve()).startswith(proj):
                            outside.append(v)
        if ev.get("type") == "result":
            cost, result = ev.get("total_cost_usd"), ev.get("subtype")
    trace_init = None
    if init is None:
        invalid.append("no init event")
    else:
        allowed = set(builtin["skills"]) | ({skill} if arm == "skill" else set())
        extra = sorted(set(init.get("skills") or []) - allowed)
        if extra:
            invalid.append(f"skills outside the allowed set: {extra}")
        if any(not str(p.get("source", "")).endswith("@builtin") for p in init.get("plugins") or []):
            invalid.append("a non-builtin plugin")
        if init.get("mcp_servers"):
            invalid.append("an MCP server")
        if set(init.get("tools") or []) - set(TOOLS.split(",")):
            invalid.append("a tool outside the list")
        if init.get("model") != MODEL:
            invalid.append(f"model {init.get('model')!r}")
        # if the probe found an init field that reflects a project CLAUDE.md, it must match the arm
        for key, plain in (builtin.get("claudemd_project_plain_values") or {}).items():
            if arm == "claudemd" and init.get(key) == plain:
                invalid.append(f"init field {key!r} does not show the project CLAUDE.md")
            if arm != "claudemd" and init.get(key) != plain:
                invalid.append(f"init field {key!r} shows project memory in the {arm} arm")
        trace_init = {"skills_beyond_builtin": sorted(set(init.get("skills") or []) - set(builtin["skills"])),
                      "plugins": [p.get("source") for p in init.get("plugins") or []],
                      "mcp_servers": init.get("mcp_servers"), "tools": init.get("tools"), "model": init.get("model"),
                      "apiKeySource": init.get("apiKeySource"), "claude_code_version": init.get("claude_code_version")}
    return {"tools": tools, "outside": outside, "cost": cost, "result": result, "invalid": invalid,
            "skill_called": "Skill" in tools, "skill_calls": skill_calls, "_trace_init": trace_init}


def compare(rows: list[dict], tasks: list[str], a: str, b: str) -> dict:
    per_task, higher, lower = {}, 0, 0
    for t in tasks:
        means = {}
        for arm in (a, b):
            xs = [r["convention"] for r in rows if r["task"] == t and r["arm"] == arm and r["convention"] is not None]
            means[arm] = sum(xs) / len(xs) if xs else None
        if means[a] is None or means[b] is None:
            per_task[t] = {**means, "diff": None}
            continue
        diff = means[a] - means[b]
        per_task[t] = {**means, "diff": round(diff, 4)}
        higher += diff > 0
        lower += diff < 0
    n = higher + lower
    p_a = sum(comb(n, k) for k in range(higher, n + 1)) / 2 ** n if n else 1.0
    p_b = sum(comb(n, k) for k in range(lower, n + 1)) / 2 ** n if n else 1.0
    return {"per_task": per_task, f"{a}_higher": higher, f"{b}_higher": lower, "ties": len(tasks) - n,
            "sign_test_p": round(p_a, 4), "sign_test_p_reverse": round(p_b, 4)}


def grade(work: Path, export: bool) -> None:
    m = json.loads((work / "mapping.json").read_text())
    builtin = json.loads(_probe_path(m["versions"]["claude_code"]).read_text())
    spec = {t["id"]: t for t in _tasks(HERE)}
    rows, traces = [], []
    for r in sorted(m["runs"], key=lambda r: r["id"]):  # graded in id order, before arms are looked up
        g = grade_one(HERE, work / r["id"] / "p", r["task"])
        conv = [a for a in spec[r["task"]]["assertions"] if a["kind"] == "convention"]
        base = [a for a in spec[r["task"]]["assertions"] if a["kind"] == "baseline"]
        rows.append({"id": r["id"], "task": r["task"], "repeat": r["repeat"],
                     "convention": sum(a["test"] in g["passed"] for a in conv) / len(conv) if conv else None,
                     "baseline": sum(a["test"] in g["passed"] for a in base) / len(base) if base else None,
                     "passed": g["passed"]})
    arm_of = {r["id"]: r["arm"] for r in m["runs"]}
    for row in rows:
        row["arm"] = arm_of[row["id"]]
        a = audit(work, row["id"], m["skill"], row["arm"], builtin)
        traces.append({"id": row["id"], "arm": row["arm"], "task": row["task"], "init": a.pop("_trace_init"),
                       "tool_calls": a["tools"], "skill_calls": a["skill_calls"]})
        row.update(a)
    valid = [r for r in rows if not r["invalid"]]
    ids = list(spec)
    primary = compare(valid, ids, "skill", "control")
    primary["verdict"] = ("SUPPORTED" if primary["skill_higher"] > primary["control_higher"]
                          and primary["sign_test_p"] < 0.05
                          else "NEGATIVE" if primary["control_higher"] >= primary["skill_higher"] else "INCONCLUSIVE")
    secondary = compare(valid, ids, "skill", "claudemd")
    secondary["verdict"] = ("SKILL_FORMAT_HIGHER" if secondary["sign_test_p"] < 0.05
                            and secondary["skill_higher"] > secondary["claudemd_higher"]
                            else "CLAUDEMD_HIGHER" if secondary["sign_test_p_reverse"] < 0.05
                            and secondary["claudemd_higher"] > secondary["skill_higher"]
                            else "NO_DIFFERENCE_SHOWN")
    tertiary = compare(valid, ids, "claudemd", "control")
    tertiary["verdict"] = ("TEXT_HIGHER" if tertiary["claudemd_higher"] > tertiary["control_higher"]
                           and tertiary["sign_test_p"] < 0.05
                           else "NEGATIVE" if tertiary["control_higher"] >= tertiary["claudemd_higher"]
                           else "INCONCLUSIVE")

    def arm_mean(arm, key):
        xs = [r[key] for r in valid if r["arm"] == arm and r[key] is not None]
        return round(sum(xs) / len(xs), 4) if xs else None

    summary = {"model": MODEL, "versions": m["versions"], "primary_skill_vs_control": primary,
               "secondary_skill_vs_claudemd": secondary, "tertiary_claudemd_vs_control": tertiary,
               "per_arm": {arm: {"convention": arm_mean(arm, "convention"), "baseline": arm_mean(arm, "baseline"),
                                 "runs": sum(r["arm"] == arm for r in rows),
                                 "skill_called": sum(r["skill_called"] for r in rows if r["arm"] == arm),
                                 "result_not_success": sum(r["result"] != "success" for r in rows
                                                          if r["arm"] == arm),
                                 "cost": round(sum(r["cost"] or 0 for r in rows if r["arm"] == arm), 4)}
                           for arm in ARMS},
               "invalid": [r["id"] for r in rows if r["invalid"]],
               "cost": round(sum(r["cost"] or 0 for r in rows), 4)}
    (work / "results.json").write_text(json.dumps(rows, indent=1))
    (work / "trace.json").write_text(json.dumps(traces, indent=1))
    (work / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    if export:
        out = HERE / "results"
        (out / "candidates").mkdir(parents=True, exist_ok=True)
        for name in ("mapping.json", "results.json", "trace.json", "summary.json"):
            shutil.copyfile(work / name, out / name)
        for r in m["runs"]:  # full streams stay local (session metadata); diffs against the arm setup commit
            proj = work / r["id"] / "p"
            _git(proj, "add", "-A", "--", ".", ":(exclude,glob)**/__pycache__/**")
            (out / "candidates" / f"{r['id']}.diff").write_text(_git(proj, "diff", "--cached", r["setup"]))


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["check", "probe", "prepare", "run", "grade"])
    ap.add_argument("--work", type=Path)
    ap.add_argument("--repo-ai", dest="exe", default=os.environ.get("REPO_AI", "repo-ai"))
    ap.add_argument("--token-file", type=Path, help="a file holding a `claude setup-token` token (chmod 600); "
                    "passed to Claude Code as CLAUDE_CODE_OAUTH_TOKEN, never printed or recorded")
    ap.add_argument("--strict", action="store_true", help="check: PENDING materials are errors (freeze gate)")
    ap.add_argument("--selftest", action="store_true", help="check: also exercise prepare and grading offline "
                    "with c10-confirm-v1's materials as a stand-in")
    ap.add_argument("--export", action="store_true", help="grade: copy results and diffs into results/")
    args = ap.parse_args()
    if args.stage == "check":
        rep = check(HERE, args.strict)
        print("-- c10-confirm-v2 materials --")
        rep.print()
        code = 1 if rep.has("ERROR") else 0
        if args.selftest:
            code = max(code, selftest())
        return code
    if not args.work:
        raise SystemExit("--work DIR is required")
    work = _work(args.work)
    if args.stage == "probe":
        work.mkdir(parents=True, exist_ok=True)
        probe(work)
    elif args.stage == "prepare":
        prepare(work, args.exe)
    elif args.stage == "run":
        if not args.token_file:
            raise SystemExit("--token-file is required (token_env); an inherited token is never used")
        run(work, _read_token(args.token_file.expanduser()))
    else:
        grade(work, args.export)
    return 0


if __name__ == "__main__":
    sys.exit(main())
