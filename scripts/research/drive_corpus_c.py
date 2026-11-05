"""Corpus C driver (protocol: docs/research/capability-discovery-C-2026-10/PROTOCOL.md).

    python scripts/research/drive_corpus_c.py CORPUS.json OUT.json [--latency-tasks 24]

For each task it produces the deterministic top-3 (`recommend`), the shortlist an agent would see
(`candidates`, K = 6) and the exact rendered text of both, with availability fields taken from the
task's environment fixture (S0/S1/S2 in env_truth.json). It then measures end-to-end CLI latency
on a category-stratified sample. Nothing here reads labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from repo_ai import capabilities as caps  # noqa: E402
from repo_ai import capdiscovery, capselect  # noqa: E402

PROTO = ROOT / "docs/research/capability-discovery-C-2026-10"
INDEXED = {"repo-ai.impact", "repo-ai.context", "repo-ai.review", "repo-ai.verify"}


def env_states(manifest: dict, env: str) -> dict:
    """Lifecycle states for one environment fixture, shaped like capabilities.state()."""
    indexed = env != "S0"
    ruff = {"S0": "not_installed", "S1": "not_approved", "S2": "ok"}[env]
    out = {}
    for c in manifest["capabilities"]:
        i = c["id"]
        review = c.get("review") or {}
        s = {"discovered": {"status": True}, "reviewed": {"status": review.get("status", "not-reviewed")},
             "invoked": {"count": 0}, "validated": {"status": "never", "measured_effect": None}}
        if c["kind"] == "builtin":
            ok = indexed or i not in INDEXED
            s["approved"] = {"status": "not-required"}
            s["available"] = {"status": ok, "reason": "ok" if ok else "needs `repo-ai init`"}
        elif i == "adapter.ruff-security":
            s["approved"] = {"status": "approved", "sha256": "0" * 16} if ruff == "ok" else {"status": "not-approved"}
            s["available"] = {"status": ruff == "ok", "reason": ruff}
        elif c["kind"] == "adapter":
            s["approved"] = {"status": "not-applicable"}
            s["available"] = {"status": False, "reason": "no_adapter"}
        else:
            s["approved"] = {"status": "not-managed"}
            s["available"] = {"status": False, "reason": "not_managed_by_repo_ai"}
        out[i] = s
    return out


def predict(task: dict, manifest: dict, stacks: dict) -> dict:
    prof = stacks.get(task["repo_stack"], {"languages": [], "frameworks": [], "dependencies": []})
    changed = list(task.get("changed_files") or [])
    states = env_states(manifest, task.get("env", "S0"))
    rec = caps.recommend(task["task"], prof, changed, manifest, states)
    disc = capdiscovery.discover(task["task"], prof, changed, manifest)
    inputs = {"task_sha256": hashlib.sha256(task["task"].encode()).hexdigest()[:16], "base": "HEAD", "commit": "",
              "changed": sorted(changed), "indexed": task.get("env", "S0") != "S0", "version": "corpus-c"}
    menu = capselect.candidates(disc, manifest, states, deny=[], digest_inputs=inputs)
    reason = {"needs `repo-ai init`": "needs-init"}
    top3 = [{"id": r["id"], "available": r["available"], "reason": reason.get(r["availability"], r["availability"])}
            for r in rec["recommended"]]
    short = [{"id": c["id"], "available": c["available"], "reason": c["reason"], "blocked": bool(c.get("blocked"))}
             for c in menu["candidates"]]
    return {"top3": top3, "shortlist": short, "rendered_top3": caps.render_recommendation(rec),
            "rendered_shortlist": capselect.encode(menu)}


def latency(tasks: list[dict], n: int) -> dict[str, list[float]]:
    """End-to-end `repo-ai capabilities recommend --json` in a small indexed fixture repository."""
    by_cat: dict[str, list[dict]] = {}
    for t in tasks:
        by_cat.setdefault(t["category"], []).append(t)
    sample: list[dict] = []
    while len(sample) < min(n, len(tasks)):
        for cat in sorted(by_cat):
            if by_cat[cat] and len(sample) < n:
                sample.append(by_cat[cat].pop(0))
    out: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "src/app.py").write_text("def main():\n    return 1\n")
        env = {**os.environ, "REPO_AI_HOME": str(Path(tmp) / "home"), "PYTHONPATH": str(ROOT / "src")}
        for k in caps.AGENT_ENV:
            env.pop(k, None)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=x@example.invalid", "-c", "user.name=x",
                        "commit", "-qm", "init"], check=True)
        subprocess.run([sys.executable, "-m", "repo_ai", "init", "-C", str(repo)], env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for t in sample:
            argv = [sys.executable, "-m", "repo_ai", "capabilities", "recommend", "--task-stdin", "--json",
                    "-C", str(repo), "--files", ",".join(t.get("changed_files") or []) or ""]
            runs = []
            for i in range(6):
                t0 = time.perf_counter()
                subprocess.run(argv, input=t["task"].encode(), env=env, check=True, stdout=subprocess.DEVNULL)
                if i:
                    runs.append(round((time.perf_counter() - t0) * 1000, 1))
            out[t["id"]] = runs
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("out")
    ap.add_argument("--latency-tasks", type=int, default=24)
    a = ap.parse_args()
    doc = json.loads(Path(a.corpus).read_text())
    manifest = caps.load_manifest()
    stacks = json.loads((PROTO / "stacks_c.json").read_text())
    preds = {t["id"]: predict(t, manifest, stacks) for t in doc["tasks"]}
    lat = latency(doc["tasks"], a.latency_tasks) if a.latency_tasks else {}
    for tid, runs in lat.items():
        preds[tid]["latency_ms"] = runs
    meta = {"shortlist_shown_to_agent": True, "lexicon_sha256": capdiscovery.lexicon_sha256(),
            "latency": f"median of 5 after 1 warm-up, {len(lat)} tasks",
            "median_ms_overall": statistics.median([statistics.median(v) for v in lat.values()]) if lat else None}
    Path(a.out).write_text(json.dumps({"meta": meta, "tasks": preds}, indent=1, sort_keys=True) + "\n")
    print(f"{len(preds)} predictions -> {a.out}; sha256 {hashlib.sha256(Path(a.out).read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
