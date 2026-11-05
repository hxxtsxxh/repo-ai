#!/usr/bin/env python3
"""Reproducible retrieval + latency benchmark for repo-ai.

    python benchmarks/run.py                      # current source tree
    python benchmarks/run.py --src /path/to/src   # another checkout's src/
    python benchmarks/run.py --out benchmarks/results/mine.json

For every fixture in tests/fixtures/ it copies the tree to a temp dir,
creates a small deterministic git history, runs `repo-ai init` without any
agent wiring, and then evaluates every case in benchmarks/gold.json:

  recall@5          share of expected files found in the first 5 results
  MRR               1 / rank of the first expected file (0 if absent)
  false injection   irrelevant prompts that still produced hook output
  hook tokens       size of the hook-format injection (chars / 4)
  latency           wall time of each CLI call (includes interpreter start)

The CLI is invoked as a subprocess exactly as a hook would invoke it, so
latency numbers include Python start-up. Nothing here touches the network.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FIXTURES = REPO / "tests" / "fixtures"


def git(cwd: Path, *args: str, date: str = "2026-01-01T12:00:00+00:00") -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
           "GIT_AUTHOR_NAME": "bench", "GIT_AUTHOR_EMAIL": "bench@example.invalid",
           "GIT_COMMITTER_NAME": "bench", "GIT_COMMITTER_EMAIL": "bench@example.invalid"}
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prepare(fixture: str, workdir: Path) -> Path:
    dest = workdir / fixture
    shutil.copytree(FIXTURES / fixture, dest)
    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    git(dest, "commit", "-qm", "initial")
    return dest


class Cli:
    def __init__(self, src: Path) -> None:
        self.env = {**os.environ, "PYTHONPATH": str(src), "NO_COLOR": "1"}
        for key in list(self.env):
            if key.startswith("REPO_AI_"):
                del self.env[key]

    def run(self, repo: Path, *args: str, stdin: str | None = None) -> tuple[float, subprocess.CompletedProcess]:
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", "repo_ai", *args, "-C", str(repo)],
                              capture_output=True, text=True, env=self.env, input=stdin,
                              check=False)
        return time.perf_counter() - started, proc

    def raw(self, cwd: Path, *args: str, stdin: str | None = None) -> tuple[float, subprocess.CompletedProcess]:
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, "-m", "repo_ai", *args], cwd=cwd,
                              capture_output=True, text=True, env=self.env, input=stdin,
                              check=False)
        return time.perf_counter() - started, proc


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[idx]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(REPO / "src"), help="directory containing repo_ai/")
    ap.add_argument("--out", default="", help="write JSON results here")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    cli = Cli(Path(args.src).resolve())
    _, ver = cli.raw(REPO, "--version")
    version = (ver.stdout or ver.stderr).strip()
    _, help_out = cli.raw(REPO, "hook", "--help")
    has_hook_cmd = help_out.returncode == 0

    gold = json.loads((HERE / "gold.json").read_text())["cases"]
    fixtures = sorted({c["fixture"] for c in gold})

    results: dict = {"label": args.label or version, "version": version,
                     "python": sys.version.split()[0], "fixtures": {}, "cases": []}
    init_times, update_times, query_times, hook_times = [], [], [], []

    with tempfile.TemporaryDirectory(prefix="repo-ai-bench-") as tmp:
        work = Path(tmp)
        repos = {}
        for fixture in fixtures:
            repo = prepare(fixture, work)
            elapsed, proc = cli.run(repo, "init", "--no-bob", "-q")
            if proc.returncode != 0:
                print(proc.stderr, file=sys.stderr)
                return 1
            init_times.append(elapsed)
            elapsed, _ = cli.run(repo, "update", "-q")
            update_times.append(elapsed)
            repos[fixture] = repo
            results["fixtures"][fixture] = {"init_s": round(init_times[-1], 3),
                                            "update_noop_s": round(elapsed, 3)}

        for case in gold:
            repo = repos[case["fixture"]]
            elapsed, proc = cli.run(repo, "context", case["prompt"], "--format", "json")
            query_times.append(elapsed)
            try:
                data = json.loads(proc.stdout or "{}")
            except json.JSONDecodeError:
                data = {}
            paths = [r["path"] for r in data.get("results", [])]
            _, hook = cli.run(repo, "context", case["prompt"], "--format", "hook")
            hook_tokens = len(hook.stdout.strip()) // 4
            row = {"fixture": case["fixture"], "kind": case["kind"], "prompt": case["prompt"][:80],
                   "top5": paths[:5], "hook_tokens": hook_tokens}
            if has_hook_cmd:
                payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": case["prompt"],
                                      "cwd": str(repo), "session_id": "bench"})
                elapsed, hproc = cli.raw(repo, "hook", "claude", "prompt", stdin=payload)
                hook_times.append(elapsed)
                row["claude_hook_chars"] = len(hproc.stdout)
            if case["kind"] == "relevant":
                expected = case["expected"]
                found = [p for p in expected if p in paths[:5]]
                row["recall@5"] = len(found) / len(expected)
                rank = next((i + 1 for i, p in enumerate(paths) if p in expected), 0)
                row["rr"] = 1.0 / rank if rank else 0.0
            else:
                injected = hook_tokens > 0 if not has_hook_cmd else row.get("claude_hook_chars", 0) > 0
                row["false_injection"] = bool(hook_tokens > 0) or injected
            results["cases"].append(row)

    relevant = [c for c in results["cases"] if c["kind"] == "relevant"]
    irrelevant = [c for c in results["cases"] if c["kind"] == "irrelevant"]
    results["summary"] = {
        "cases": len(results["cases"]),
        "recall@5": round(statistics.mean(c["recall@5"] for c in relevant), 3),
        "mrr": round(statistics.mean(c["rr"] for c in relevant), 3),
        "false_injection_rate": round(statistics.mean(c["false_injection"] for c in irrelevant), 3),
        "relevant_injection_rate": round(statistics.mean(
            (c.get("claude_hook_chars", c["hook_tokens"]) > 0) for c in relevant), 3),
        "hook_tokens_mean_relevant": round(statistics.mean(c["hook_tokens"] for c in relevant), 1),
        "hook_tokens_max": max(c["hook_tokens"] for c in results["cases"]),
        "init_s_p50": round(pct(init_times, 0.5), 3),
        "update_noop_s_p50": round(pct(update_times, 0.5), 3),
        "query_s_p50": round(pct(query_times, 0.5), 3),
        "query_s_p95": round(pct(query_times, 0.95), 3),
    }
    if hook_times:
        results["summary"]["claude_hook_s_p50"] = round(pct(hook_times, 0.5), 3)
        results["summary"]["claude_hook_s_p95"] = round(pct(hook_times, 0.95), 3)

    print(f"repo-ai benchmark — {results['label']} (python {results['python']})")
    for key, value in results["summary"].items():
        print(f"  {key:28s} {value}")
    misses = [c for c in relevant if c["recall@5"] < 1.0]
    if misses:
        print("  incomplete recall:")
        for c in misses:
            print(f"    [{c['fixture']}] {c['prompt'][:60]!r} -> {c['top5']}")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
