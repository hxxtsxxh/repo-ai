#!/usr/bin/env python3
"""verify-eval harness (PROTOCOL.md). Offline; every test run happens in a
network-less podman container. Needs: git, podman with the pinned python and
node images, and repo-ai importable (the build under evaluation).

    VEV_WORK=/path/to/work python harness.py all <project> [...]
    VEV_WORK=... python harness.py score [--set dev|heldout]

$VEV_WORK/repos/<project> must be a clone of the corpus URL (the harness
checks out the pinned commit). Results go to $VEV_WORK/out/<project>/.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import random
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repo_ai import sandbox
from repo_ai.verify.runner import resolve
from repo_ai.verify.select import classify

HERE = Path(__file__).resolve().parent
CORPUS = json.loads((HERE / "corpus.json").read_text("utf-8"))["projects"]
WORK = Path(os.environ.get("VEV_WORK", "")).resolve()
RA = shutil.which("repo-ai") or "repo-ai"
# the previous release, for the impact-0.7.7 baseline (its own index, in its own copy)
RA_OLD = os.environ.get("VEV_OLD_RA", str(Path.home() / ".local" / "bin" / "repo-ai"))
CODE = {".py", ".js", ".mjs", ".cjs", ".ts", ".mts"}
N_MUTANTS, N_REVERTS = 20, 10
# post-hoc re-scoring writes and reads selections-<tag>.json; the frozen selections.json is never touched
SEL = "selections" + (f"-{os.environ['VEV_SELECTIONS_TAG']}" if os.environ.get("VEV_SELECTIONS_TAG") else "")


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    return p.stdout


def env() -> dict[str, str]:
    """repo-ai runs with an isolated HOME (no user config, registry or caches).
    The container CLI it may start (`verify --sandbox podman`) still needs its
    own connection settings: only those directories are linked in."""
    home = WORK / "home"
    real = Path.home()
    for rel in (".config/containers", ".local/share/containers"):
        link, target = home / rel, real / rel
        if target.is_dir() and not link.exists():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target, target_is_directory=True)
    return {**os.environ, "HOME": str(home), "REPO_AI_NO_BACKGROUND": "1"}


def out_dir(name: str) -> Path:
    d = WORK / "out" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def load(name: str, what: str):
    return json.loads((out_dir(name) / f"{what}.json").read_text("utf-8"))


def save(name: str, what: str, data) -> None:
    (out_dir(name) / f"{what}.json").write_text(json.dumps(data, indent=1, sort_keys=True), "utf-8")


def backend_for(name: str):
    """The network-less container for a project: its own image when the corpus
    names one (held-out-3: dependencies baked in), else the pinned stdlib image."""
    lang = CORPUS[name]["lang"]
    image = CORPUS[name].get("image")
    return sandbox.get_backend("podman", images={lang: image} if image else None, toolchain=lang)


def runner_for(name: str):
    proj = CORPUS[name]
    r = resolve(WORK / "repos" / name, proj["test_command"])
    r.excluded = list(proj.get("excluded_tests", []))
    return r


# --------------------------------------------------------------------------
def setup(name: str) -> None:
    repo = WORK / "repos" / name
    pin = CORPUS[name]["commit"]
    git(repo, "checkout", "-q", "--detach", pin)
    git(repo, "reset", "-q", "--hard", pin)
    git(repo, "clean", "-qfdx")
    (WORK / "home").mkdir(exist_ok=True)
    t = time.time()
    p = subprocess.run([RA, "init", "--agent", "none", "-q"], cwd=repo, env=env(), capture_output=True, text=True)
    init_s = time.time() - t
    if p.returncode:
        raise RuntimeError(p.stderr[-500:])
    if git(repo, "status", "--porcelain", "--", ".gitignore").strip():
        git(repo, "add", ".gitignore")
        git(repo, "-c", "user.email=e@e", "-c", "user.name=e", "commit", "-qm", "eval setup")
    old = WORK / "old" / name
    if old.exists():
        shutil.rmtree(old)
    shutil.copytree(repo, old, symlinks=True, ignore=shutil.ignore_patterns(".repo-ai"))
    subprocess.run([RA_OLD, "init", "--agent", "none", "-q"], cwd=old, env=env(), capture_output=True, text=True,
                   check=True)
    old_version = subprocess.run([RA_OLD, "--version"], capture_output=True, text=True).stdout.strip()
    files = [f for f in git(repo, "ls-files").split("\n") if f]
    runner = runner_for(name)
    tests = runner.test_files(files)
    save(name, "setup", {"snapshot": git(repo, "rev-parse", "HEAD").strip(), "pin": pin, "init_s": round(init_s, 2),
                         "runner": runner.to_json(), "tests": tests, "files": len(files),
                         "old_release": old_version})
    print(f"{name}: {len(tests)} test files, init {init_s:.1f}s")


def _copy(name: str, tag: str) -> Path:
    dest = WORK / "tmp" / f"{name}-{tag}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(WORK / "repos" / name, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".repo-ai", "node_modules", "__pycache__"))
    _install_metadata(dest)
    return dest


def _install_metadata(dest: Path) -> None:
    """Environment, not selection: a project that declares entry points finds its
    plugins through installed distribution metadata. The sandbox image has no
    install of the project, so write the metadata an install would create
    (generic rule; applied to every project that declares entry points)."""
    import tomllib
    try:
        data = tomllib.loads((dest / "pyproject.toml").read_text("utf-8"))
    except (OSError, ValueError):
        return
    project = data.get("project") or {}
    groups = project.get("entry-points") or {}
    if not groups or not project.get("name"):
        return
    dist = dest / f"{project['name'].replace('-', '_')}-0.0.0.dist-info"
    dist.mkdir(exist_ok=True)
    (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {project['name']}\nVersion: 0.0.0\n", "utf-8")
    lines = []
    for group, entries in groups.items():
        lines.append(f"[{group}]")
        lines += [f"{k} = {v}" for k, v in entries.items()]
        lines.append("")
    (dist / "entry_points.txt").write_text("\n".join(lines), "utf-8")


DRIVER_PY = r'''
import json, re, subprocess, sys, time
spec = json.load(open(sys.argv[1])); out = {}
for run in spec["runs"]:
    argv = [sys.executable if a == "python" else a for a in run["argv"]]
    t = time.time()
    try:
        p = subprocess.run(argv, cwd=spec["cwd"] or ".", capture_output=True, text=True, timeout=spec["timeout"],
                           env={**__import__("os").environ, **spec.get("env", {})})
        rc, text = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        rc, text = -9, "TIMEOUT"
    m = re.findall(r"Ran (\d+) tests?", text)
    ran = int(m[-1]) if m else None
    if ran is None:  # pytest: "3 passed, 1 failed, 2 errors in 0.1s"; "no tests ran"
        counts = re.findall(r"(\d+) (passed|failed|errors?|xfailed|xpassed)", text)
        ran = sum(int(n) for n, _ in counts) if counts else (0 if "no tests ran" in text else None)
    out[run["test"]] = {"exit": rc, "dur": round(time.time() - t, 3), "ran": ran,
                        "tail": text[-400:] if rc else ""}
json.dump(out, open(sys.argv[2], "w"))
'''

DRIVER_NODE = r'''
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
const spec = JSON.parse(readFileSync(process.argv[2], "utf8")); const out = {};
for (const run of spec.runs) {
  const argv = run.argv.map(a => a === "node" ? process.execPath : a);
  const t = Date.now();
  const p = spawnSync(argv[0], argv.slice(1), { cwd: spec.cwd || ".", encoding: "utf8", timeout: spec.timeout * 1000,
                                               env: { ...process.env, ...(spec.env || {}) } });
  const text = (p.stdout || "") + (p.stderr || "");
  const m = [...text.matchAll(/(?:# |ℹ )tests (\d+)/g)];
  const rc = p.status === null ? -9 : p.status;
  out[run.test] = { exit: rc, dur: (Date.now() - t) / 1000, ran: m.length ? Number(m[m.length - 1][1]) : null,
                    tail: rc ? text.slice(-400) : "" };
}
writeFileSync(process.argv[3], JSON.stringify(out));
'''


def run_tests(name: str, workdir: Path, tests: list[str]) -> dict:
    """Every test file individually, in one network-less container."""
    runner = runner_for(name)
    lang = CORPUS[name]["lang"]
    ev = workdir / ".eval"
    ev.mkdir(exist_ok=True)
    driver = ev / ("driver.py" if lang == "python" else "driver.mjs")
    driver.write_text(DRIVER_PY if lang == "python" else DRIVER_NODE, "utf-8")
    spec = {"cwd": runner.cwd, "timeout": 300, "env": runner.env,
            "runs": [{"test": t, "argv": runner.file_argv(t)} for t in tests]}
    (ev / "spec.json").write_text(json.dumps(spec), "utf-8")
    backend = backend_for(name)
    head = ["python"] if lang == "python" else ["node"]
    res = backend.run([*head, f"/work/.eval/{driver.name}", "/work/.eval/spec.json", "/work/.eval/result.json"],
                      workdir, limits=sandbox.Limits(timeout_s=7200, memory_mb=4096, cpus=2, pids=2048),
                      toolchain=lang if lang == "node" else "python")
    try:
        return json.loads((ev / "result.json").read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{name}: driver failed: {res.stderr[-800:]}") from exc


def baseline(name: str) -> None:
    tests = load(name, "setup")["tests"]
    work = _copy(name, "base")
    res = run_tests(name, work, tests)
    shutil.rmtree(work, ignore_errors=True)
    failing = sorted(t for t, r in res.items() if r["exit"] != 0)
    empty = sorted(t for t, r in res.items() if r["exit"] == 0 and r.get("ran") == 0)
    save(name, "baseline", res)
    print(f"{name}: baseline {len(tests) - len(failing)}/{len(tests)} pass "
          f"({sum(r['dur'] for r in res.values()):.1f}s); failing: {failing[:6]}; ran-0: {empty[:4]}")


def record(name: str) -> None:
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor
    from repo_ai.verify.testmap import record as rec
    work = _copy(name, "record")
    backend = backend_for(name)
    t = time.time()
    ws = isolate.materialize(work, label="vev-record")  # the engine runs tests only in a disposable copy
    try:
        ex = Executor(backend, work, python="python", node="node", timeout_s=600).in_workspace(ws)
        tmap = rec(work, runner_for(name), ex, load(name, "setup")["tests"], workers=3)
    finally:
        ws.cleanup()
    secs = time.time() - t
    tmap.save(out_dir(name) / "testmap.json")
    shutil.rmtree(work, ignore_errors=True)
    meta = load(name, "setup")
    meta["record_s"] = round(secs, 1)
    save(name, "setup", meta)
    print(f"{name}: recorded {len(tmap.tests)} test files in {secs:.0f}s; failing at record: {tmap.baseline_failures()[:5]}")


# --------------------------------------------------------------------------
# images (held-out-3: dependency-based projects)
# --------------------------------------------------------------------------
def build_image(name: str) -> None:
    """Build the project's test image (network only during this build), then
    record its digest and installed packages. Python: pytest and the test
    requirements named in the corpus. JS: `npm ci --ignore-scripts` into
    /node_modules, which node finds by walking up from /work."""
    proj = CORPUS[name]
    image = proj.get("image")
    if not image:
        print(f"{name}: no image in the corpus (stdlib image)")
        return
    repo = WORK / "repos" / name
    ctx = WORK / "images" / name
    if ctx.exists():
        shutil.rmtree(ctx)
    ctx.mkdir(parents=True)
    if proj["lang"] == "python":
        reqs = " ".join(shlex.quote(r) for r in proj.get("test_requirements", ["pytest"]))
        (ctx / "Containerfile").write_text(
            "FROM docker.io/library/python:3.12-slim\n"
            f"RUN pip install --no-cache-dir --disable-pip-version-check {reqs}\n", "utf-8")
        listing = ["pip", "freeze"]
    else:
        for f in ("package.json", "package-lock.json"):
            if (repo / f).exists():
                shutil.copy2(repo / f, ctx / f)
        install = "npm ci --ignore-scripts" if (ctx / "package-lock.json").exists() else \
            "npm install --ignore-scripts --no-audit --no-fund"
        (ctx / "Containerfile").write_text(
            "FROM docker.io/library/node:24-slim\nWORKDIR /\nCOPY package*.json /\n"
            f"RUN {install} && rm -f /package.json /package-lock.json\n"
            # held-out-6 (before measurement): a package's own binaries (jest, ...) are on PATH, as npm runs them
            "ENV PATH=/node_modules/.bin:$PATH\n", "utf-8")
        listing = ["sh", "-c", "cd / && ls node_modules | head -400"]
    subprocess.run(["podman", "build", "-q", "-t", image, str(ctx)], check=True)
    digest = subprocess.run(["podman", "image", "inspect", "--format", "{{.Digest}}", image],
                            capture_output=True, text=True, check=True).stdout.strip()
    packages = subprocess.run(["podman", "run", "--rm", "--network", "none", image, *listing],
                              capture_output=True, text=True, check=False).stdout.split()
    save(name, "image", {"image": image, "digest": digest, "packages": packages,
                         "containerfile": (ctx / "Containerfile").read_text("utf-8")})
    print(f"{name}: image {image} {digest[:19]}… ({len(packages)} packages)")


# --------------------------------------------------------------------------
# change generators (fixed rules; PROTOCOL.md)
# --------------------------------------------------------------------------
def _sources(name: str) -> list[str]:
    repo = WORK / "repos" / name
    files = [f for f in git(repo, "ls-files").split("\n") if f]
    universe = set(load(name, "setup")["tests"])
    runner = runner_for(name)
    out = []
    for f in files:
        p = Path(f)
        if p.suffix not in CODE or f.endswith(".d.ts") or p.name in {"setup.py", "conftest.py", "noxfile.py"}:
            continue
        if any(part in {"docs", "doc", "benchmark", "benchmarks", "bench", "examples", "example", "scripts",
                        "tools", "build", "dist", "site"} for part in p.parts[:-1]):
            continue
        if classify(f, universe, runner) == "source":
            out.append(f)
    return out


_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
         ast.Add: ast.Sub, ast.Sub: ast.Add, ast.And: ast.Or, ast.Or: ast.And}


def _py_sites(text: str) -> list[tuple[int, int, int, str]]:
    """(line, start_col, end_col, replacement) for single-line sites inside functions."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.split("\n")
    sites = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if getattr(node, "lineno", None) is None or node.lineno != getattr(node, "end_lineno", -1):
                continue
            if node is fn:
                continue
            new = None
            if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _SWAP:
                m = copy.deepcopy(node)
                m.ops = [_SWAP[type(node.ops[0])]()]
                new = ast.unparse(m)
            elif isinstance(node, ast.BinOp) and type(node.op) in _SWAP:
                m = copy.deepcopy(node)
                m.op = _SWAP[type(node.op)]()
                new = "(" + ast.unparse(m) + ")"
            elif isinstance(node, ast.BoolOp) and type(node.op) in _SWAP:
                m = copy.deepcopy(node)
                m.op = _SWAP[type(node.op)]()
                new = "(" + ast.unparse(m) + ")"
            elif isinstance(node, ast.Constant) and type(node.value) is int:
                new = repr(node.value + 1)
            elif isinstance(node, ast.Return) and node.value is not None and not (
                    isinstance(node.value, ast.Constant) and node.value.value is None):
                new = "return None"
            if new is None:
                continue
            line = lines[node.lineno - 1].encode("utf-8")
            seg = line[node.col_offset:node.end_col_offset].decode("utf-8", "replace")
            if seg.strip() and seg != new:
                sites.append((node.lineno, node.col_offset, node.end_col_offset, new))
    return sites


_JS_FLIPS = [(r"===", "!=="), (r"!==", "==="), (r" < ", " <= "), (r" > ", " >= "), (r" <= ", " < "),
             (r" >= ", " > "), (r" \+ 1\b", " - 1"), (r" - 1\b", " + 1"), (r"\btrue\b", "false"),
             (r"\bfalse\b", "true"), (r" && ", " || "), (r" \|\| ", " && ")]


def _js_sites(text: str) -> list[tuple[int, int, int, str]]:
    sites = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s or s.startswith(("//", "*", "/*", "import ", "export {")):
            continue
        for pat, rep in _JS_FLIPS:
            for m in re.finditer(pat, line):
                sites.append((i, m.start(), m.end(), rep))
    return sites


def gen_changes(name: str) -> None:
    repo = WORK / "repos" / name
    rng = random.Random(f"verify-eval:{name}")
    sources = _sources(name)
    changes = []
    # operator mutations
    cands = []
    for f in sources:
        text = (repo / f).read_text("utf-8", errors="replace")
        sites = _py_sites(text) if f.endswith(".py") else _js_sites(text)
        cands += [(f, s) for s in sites]
    rng.shuffle(cands)
    for f, (line, a, b, rep) in cands[:N_MUTANTS]:
        text = (repo / f).read_text("utf-8")
        lines = text.split("\n")
        raw = lines[line - 1].encode("utf-8") if f.endswith(".py") else lines[line - 1]
        if f.endswith(".py"):
            lines[line - 1] = (raw[:a] + rep.encode() + raw[b:]).decode("utf-8")  # type: ignore[operator]
        else:
            lines[line - 1] = raw[:a] + rep + raw[b:]  # type: ignore[operator]
        changes.append({"id": f"mut-{len(changes):02d}", "kind": "mutation", "detail": f"{f}:{line} -> {rep}",
                        "files": {f: "\n".join(lines)}})
    # real reverts
    srcset = set(sources)
    commits = git(repo, "log", "--no-merges", "--format=%H", "-n", "400", CORPUS[name]["commit"]).split()
    reverts = 0
    for c in commits:
        if reverts >= N_REVERTS:
            break
        stat = [ln.split("\t") for ln in git(repo, "show", "--numstat", "--format=", c).split("\n") if ln.strip()]
        src = [(int(a) if a.isdigit() else 999, int(b) if b.isdigit() else 999, p) for a, b, p in stat if p in srcset]
        if not (1 <= len(src) <= 5) or not (2 <= sum(a + b for a, b, _ in src) <= 200):
            continue
        diff = subprocess.run(["git", "diff", f"{c}^", c, "--", *[p for _, _, p in src]], cwd=repo,
                              capture_output=True, check=False).stdout
        if not diff:
            continue
        chk = subprocess.run(["git", "apply", "-R", "--check"], cwd=repo, input=diff, capture_output=True, check=False)
        if chk.returncode != 0:
            continue
        subprocess.run(["git", "apply", "-R"], cwd=repo, input=diff, capture_output=True, check=True)
        files = {}
        for _, _, p in src:
            files[p] = (repo / p).read_text("utf-8") if (repo / p).exists() else None
        git(repo, "checkout", "-q", "--", ".")
        subject = git(repo, "log", "-1", "--format=%s", c).strip()[:100]
        changes.append({"id": f"rev-{reverts:02d}", "kind": "revert", "detail": f"revert {c[:10]}: {subject}",
                        "files": files})
        reverts += 1
    git(repo, "checkout", "-q", "--", ".")
    save(name, "changes", changes)
    print(f"{name}: {sum(c['kind'] == 'mutation' for c in changes)} mutations, {reverts} reverts")


def _apply(dest: Path, change: dict) -> None:
    for p, content in change["files"].items():
        target = dest / p
        if content is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, "utf-8")


def truth(name: str, workers: int = 3) -> None:
    tests = load(name, "setup")["tests"]
    base = load(name, "baseline")
    changes = load(name, "changes")
    passing = [t for t in tests if base.get(t, {}).get("exit") == 0]

    def one(change):
        work = _copy(name, change["id"])
        _apply(work, change)
        res = run_tests(name, work, passing)
        shutil.rmtree(work, ignore_errors=True)
        affected = sorted(t for t, r in res.items() if r["exit"] != 0)
        return change["id"], {"affected": affected, "timeouts": sorted(t for t, r in res.items() if r["exit"] == -9)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        out = dict(pool.map(one, changes))
    save(name, "truth", out)
    det = sum(1 for v in out.values() if v["affected"])
    print(f"{name}: {det}/{len(changes)} changes detected by at least one test")


# --------------------------------------------------------------------------
def _grep(name: str, repo: Path, change: dict, tests: list[str]) -> list[str]:
    sel = set()
    texts = {t: (repo / t).read_text("utf-8", errors="replace") for t in tests}
    for path, content in change["files"].items():
        p = Path(path)
        if p.suffix == ".py":
            parts = list(p.with_suffix("").parts)
            if parts[0] in {"src", "lib"} and len(parts) > 1:
                parts = parts[1:]  # src layout: imported without the src/ prefix
            if parts[-1] == "__init__":
                parts = parts[:-1]
            mod = ".".join(parts)
            leaf = parts[-1] if parts else ""
            pkg = ".".join(parts[:-1])
            pat = [rf"import\s+{re.escape(mod)}\b", rf"from\s+{re.escape(mod)}\s+import"]
            if pkg:
                pat.append(rf"from\s+{re.escape(pkg)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b")
            rx = re.compile("|".join(pat))
            names = set(re.findall(r"^\s*(?:async\s+)?def\s+(\w+)", content or "", re.M))
            old = set()
            try:
                base_text = (repo / path).read_text("utf-8")
                fn_lines = {}
                for n in ast.walk(ast.parse(base_text)):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fn_lines[n.name] = (n.lineno, n.end_lineno)
                new_lines = (content or "").split("\n")
                old_lines = base_text.split("\n")
                for nm, (a, b) in fn_lines.items():
                    if old_lines[a - 1:b] != new_lines[a - 1:b]:
                        old.add(nm)
            except (OSError, SyntaxError):
                pass
            for t, text in texts.items():
                if rx.search(text) or any(re.search(rf"\b{re.escape(n)}\b", text) for n in old):
                    sel.add(t)
            del names
        else:
            stem = p.stem
            for t, text in texts.items():
                if re.search(rf"""['"][^'"]*\b{re.escape(stem)}(\.[mc]?[jt]s)?['"]""", text):
                    sel.add(t)
    return sorted(sel)


def select_all(name: str) -> None:
    repo = WORK / "repos" / name
    meta = load(name, "setup")
    tests = meta["tests"]
    changes = load(name, "changes")
    cmd = CORPUS[name]["test_command"]
    state = repo / ".repo-ai" / "state"
    tm_src = out_dir(name) / "testmap.json"
    results = {}
    for change in changes:
        _apply(repo, change)
        row: dict = {}
        try:
            row["grep"] = {"selected": _grep(name, repo, change, tests)}
            files = [p for p in change["files"]]
            t = time.time()
            old = WORK / "old" / name
            _apply(old, change)
            p = subprocess.run([RA_OLD, "impact", *files, "--format", "json"], cwd=old, env=env(),
                               capture_output=True, text=True)
            git(old, "checkout", "-q", "--", ".")
            subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=old, check=False)
            try:
                imp = json.loads(p.stdout)
                row["impact-0.7.7"] = {"selected": sorted({x["path"] for x in imp.get("tests", [])} & set(tests)),
                                       "risk": imp.get("risk"), "latency_s": round(time.time() - t, 3)}
            except ValueError:
                row["impact-0.7.7"] = {"selected": [], "error": p.stderr[-200:]}
            for method, use_rt in (("verify-static", False), ("verify-runtime", True)):
                tm = state / "testmap.json"
                if use_rt:
                    shutil.copy2(tm_src, tm)
                elif tm.exists():
                    tm.unlink()
                t = time.time()
                args = [RA, "verify", "--json", "--test-command", cmd] + (["--no-runtime"] if not use_rt else [])
                p = subprocess.run(args, cwd=repo, env=env(), capture_output=True, text=True)
                lat = time.time() - t
                try:
                    plan = json.loads(p.stdout)
                except ValueError:
                    row[method] = {"selected": [], "error": (p.stderr or p.stdout)[-300:]}
                    continue
                excluded = set(CORPUS[name].get("excluded_tests", []))
                row[method] = {"selected": sorted(s["test"] for s in plan["selected"] if s["test"] not in excluded),
                               "confidence": plan["confidence"], "triggers": plan["triggers"],
                               "latency_s": round(lat, 3),
                               "reasons": {s["test"]: sorted({r["kind"] for r in s["reasons"]}) for s in plan["selected"]}}
        finally:
            git(repo, "checkout", "-q", "--", ".")
            subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=repo, check=False)
            tm = state / "testmap.json"
            if tm.exists():
                tm.unlink()
        results[change["id"]] = row
    save(name, SEL, results)
    print(f"{name}: selections computed for {len(results)} changes")


# --------------------------------------------------------------------------
def score(which: str | None) -> dict:
    rows = {}
    agg: dict[str, dict] = {}
    names = [n for n, p in CORPUS.items() if which in (None, p["set"])]
    detail = []
    for name in names:
        try:
            meta, base, truth_, sel, changes = (load(name, "setup"), load(name, "baseline"), load(name, "truth"),
                                                load(name, SEL), load(name, "changes"))
        except OSError:
            continue
        tests = [t for t in meta["tests"] if base.get(t, {}).get("exit") == 0]
        dur = {t: base[t]["dur"] for t in tests}
        total = sum(dur.values()) or 1.0
        kinds = {c["id"]: c["kind"] for c in changes}
        for cid, s in sel.items():
            affected = set(truth_[cid]["affected"])
            methods = dict(s)
            methods["all"] = {"selected": tests, "confidence": "-"}
            for base_m in ("verify-static", "verify-runtime"):
                m = s.get(base_m) or {}
                full = m.get("confidence") == "low"
                methods["policy-" + base_m.split("-")[1]] = {
                    "selected": tests if full else m.get("selected", []), "confidence": m.get("confidence"),
                    "full": full}
            for meth, m in methods.items():
                chosen = set(m.get("selected") or []) & set(tests)
                a = agg.setdefault(meth, {"changes": 0, "detected": 0, "no_miss": 0, "recall": 0.0,
                                          "files": 0.0, "time": 0.0, "by_conf": {}, "undetected_selected": 0.0,
                                          "latency": []})
                a["changes"] += 1
                share_t = sum(dur.get(t, 0) for t in chosen) / total
                a["time"] += share_t
                a["files"] += len(chosen) / max(len(tests), 1)
                if m.get("latency_s") is not None:
                    a["latency"].append(m["latency_s"])
                if not affected:
                    continue
                a["detected"] += 1
                ok = affected <= chosen
                a["no_miss"] += ok
                a["recall"] += len(affected & chosen) / len(affected)
                conf = m.get("confidence") or "-"
                bc = a["by_conf"].setdefault(conf, [0, 0])
                bc[0] += 1
                bc[1] += 0 if ok else 1
                if meth in {"verify-runtime", "verify-static"} and not ok:
                    detail.append({"project": name, "change": cid, "kind": kinds[cid], "method": meth,
                                   "confidence": conf, "missed": sorted(affected - chosen)[:5],
                                   "triggers": (m.get("triggers") or [])[:2]})
    for meth, a in agg.items():
        d = max(a["detected"], 1)
        rows[meth] = {"changes": a["changes"], "detected": a["detected"],
                      "no_miss_rate": round(a["no_miss"] / d, 3), "mean_recall": round(a["recall"] / d, 3),
                      "selected_file_share": round(a["files"] / max(a["changes"], 1), 3),
                      "suite_time_share": round(a["time"] / max(a["changes"], 1), 3),
                      "misses_by_confidence": {k: f"{v[1]} missed of {v[0]}" for k, v in sorted(a["by_conf"].items())},
                      "median_latency_s": round(statistics.median(a["latency"]), 3) if a["latency"] else None}
    return {"set": which or "all", "projects": names, "methods": rows, "verify_misses": detail}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["image", "setup", "baseline", "record", "changes", "truth", "select", "all",
                                     "score"])
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--set", choices=["dev", "heldout", "heldout2", "heldout3", "heldout4", "heldout5", "heldout6"])
    args = ap.parse_args()
    if not WORK or not (WORK / "repos").is_dir():
        sys.exit("set VEV_WORK to a directory containing repos/<project> clones")
    if args.step == "score":
        print(json.dumps(score(args.set), indent=1))
        return 0
    steps = {"image": [build_image], "setup": [setup], "baseline": [baseline], "record": [record],
             "changes": [gen_changes], "truth": [truth], "select": [select_all],
             "all": [setup, baseline, record, gen_changes, truth, select_all]}[args.step]
    for name in args.projects:
        for step in steps:
            step(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
