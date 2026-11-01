#!/usr/bin/env python3
"""Profile `repo-ai verify --run`'s fixed cost on a small generated pytest project (C16).

Builds a 40-test project with its own virtualenv, then reports:
- wall-clock medians of the CLI (`--version`; verify after a comment-only change, after a behaviour change, and
  re-verifying an unchanged state);
- one traced cold run: every subprocess (start, duration, argv) and the in-process profile (top functions by own time);
- pytest's own start-up natively and under the sandbox prefix verify uses.

    python scripts/profile_verify.py --work DIR --out profile.json [--runs 7]

Generated code only (no third-party project); pytest is installed from PyPI into the project's own venv.
"""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import statistics
import subprocess
import sys
import time
from pathlib import Path

ENV = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}
ENV["REPO_AI_NO_BACKGROUND"] = "1"
GIT_ENV = {**ENV, "GIT_AUTHOR_NAME": "p", "GIT_AUTHOR_EMAIL": "p@example.invalid", "GIT_COMMITTER_NAME": "p",
           "GIT_COMMITTER_EMAIL": "p@example.invalid"}
RAI = [sys.executable, "-c", "import sys; from repo_ai.cli import main; sys.exit(main(sys.argv[1:]))"]


def project(work: Path) -> Path:
    root = work / "toy"
    (root / "src" / "toy").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "toy"\nversion = "0.1"\n'
                                         '[tool.pytest.ini_options]\npythonpath = ["src"]\ntestpaths = ["tests"]\n')
    (root / "src" / "toy" / "__init__.py").write_text("")
    for i in range(1, 9):
        (root / "src" / "toy" / f"m{i}.py").write_text(f"def f{i}(x):\n    return x + {i}\n")
        body = f"from toy.m{i} import f{i}\n\n" + "".join(
            f"\ndef test_{i}_{j}():\n    assert f{i}({j}) == {i + j}\n" for j in range(1, 6))
        (root / "tests" / f"test_m{i}.py").write_text(body)
    (root / ".gitignore").write_text(".venv/\n__pycache__/\n")
    subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=root, check=True)
    subprocess.run([str(root / ".venv/bin/python"), "-m", "pip", "install", "-q", "pytest"], cwd=root, check=True)
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=root, check=True, env=GIT_ENV)
    subprocess.run([*RAI, "init", "--agent", "none", "-q"], cwd=root, check=True, env=ENV)
    for args in (["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=root, check=True, env=GIT_ENV)
    return root


def median_wall(root: Path, args: list[str], runs: int) -> dict:
    times, code = [], None
    for _ in range(runs):
        t = time.perf_counter()
        code = subprocess.run([*RAI, *args], cwd=root, env=ENV, capture_output=True).returncode
        times.append(time.perf_counter() - t)
    return {"median_s": round(statistics.median(times), 3), "min_s": round(min(times), 3), "exit": code}


def traced(root: Path) -> dict:
    """One cold verify run in this process: subprocess timeline and own-time profile."""
    log: list[tuple[float, float, str]] = []
    t0 = time.perf_counter()
    real = subprocess.Popen

    class Timed(real):  # type: ignore[misc, valid-type]
        def __init__(self, args, *a, **k):
            self._t, self._a = time.perf_counter(), args
            super().__init__(args, *a, **k)

        def wait(self, *a, **k):
            r = super().wait(*a, **k)
            if not getattr(self, "_logged", False):
                self._logged = True
                argv = self._a if isinstance(self._a, str) else " ".join(map(str, self._a))
                log.append((round(self._t - t0, 3), round(time.perf_counter() - self._t, 3), argv.splitlines()[0][:160]))
            return r

    subprocess.Popen = Timed  # type: ignore[misc]
    cwd = os.getcwd()
    prof = cProfile.Profile()
    try:
        os.chdir(root)
        from repo_ai.cli import main
        import contextlib
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            prof.enable()
            try:
                main(["verify", "--run", "--rerun", "--json"])
            except SystemExit:
                pass
            prof.disable()
    finally:
        os.chdir(cwd)
        subprocess.Popen = real  # type: ignore[misc]
    total = time.perf_counter() - t0
    out = io.StringIO()
    pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(25)
    return {"total_s": round(total, 3), "subprocess_count": len(log),
            "subprocess_s": round(sum(d for _, d, _ in log), 3), "subprocesses": log,
            "top_own_time": out.getvalue().splitlines()[-40:]}


def pytest_startup(root: Path, runs: int) -> dict:
    """pytest's own start-up natively and under a minimal bubblewrap prefix (Linux): the floor of each process."""
    import shutil
    cmd = [str(root / ".venv/bin/python"), "-m", "pytest", "--version"]
    out = {"native": median_wall_cmd(cmd, root, runs), "bwrap_minimal": None}
    exe = shutil.which("bwrap") if sys.platform.startswith("linux") else None
    if exe:
        bw = [exe, "--die-with-parent", "--unshare-net", "--unshare-pid", "--ro-bind", "/", "/",
              "--proc", "/proc", "--dev", "/dev", "--bind", str(root), str(root), "--"]
        out["bwrap_minimal"] = median_wall_cmd([*bw, *cmd], root, runs)
    return out


def median_wall_cmd(cmd: list[str], cwd: Path, runs: int) -> dict:
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True)
        times.append(time.perf_counter() - t)
    return {"median_s": round(statistics.median(times), 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=7)
    a = ap.parse_args()
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    root = project(work)
    m3 = root / "src" / "toy" / "m3.py"
    orig = m3.read_text()
    res: dict = {"python": sys.version.split()[0], "platform": sys.platform, "cpus": os.cpu_count()}
    res["version"] = median_wall(root, ["--version"], a.runs)
    m3.write_text(orig.replace("x + 3", "x + 3  # c"))
    res["verify_comment_only"] = median_wall(root, ["verify", "--run", "--rerun", "--json"], a.runs)
    m3.write_text(orig.replace("x + 3", "x + 30"))
    res["verify_behaviour"] = median_wall(root, ["verify", "--run", "--rerun", "--json"], a.runs)
    res["verify_reuse"] = median_wall(root, ["verify", "--run", "--json"], a.runs)
    res["native_suite"] = median_wall_cmd([str(root / ".venv/bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                          root, a.runs)
    res["traced_behaviour_rerun"] = traced(root)
    m3.write_text(orig.replace("x + 3", "x + 3  # c"))
    res["traced_comment_only_rerun"] = traced(root)
    m3.write_text(orig)
    res["pytest_startup"] = pytest_startup(root, a.runs)
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    summary = {k: v for k, v in res.items() if not k.startswith("traced")}
    for k in ("traced_behaviour_rerun", "traced_comment_only_rerun"):
        t = res[k]
        summary[k] = {"total_s": t["total_s"], "subprocess_count": t["subprocess_count"], "subprocess_s": t["subprocess_s"]}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
