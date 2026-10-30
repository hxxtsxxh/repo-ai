"""Build / verify the preregistration manifest for abc-v1.

``python make_manifest.py write``   (re)generate manifest.json  (only before any live run)
``python make_manifest.py verify``  exit 1 if any task/hidden/grader byte changed.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARMS = {
    "A": "provider's ordinary workflow, same model/tools/budget, no repo-ai",
    "B": "same provider via `repo-ai do` (retrieval, plan, frozen verification, isolation)",
    "C": "B plus selective multi-agent/tournament; NOT RUNNABLE live in this release "
         "(compare_candidates is replay-only) -> reported NOT_RUN",
}
SEED = 20261028


def _h(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def digests() -> dict[str, str]:
    files = [p for p in sorted((HERE / "tasks").rglob("*")) if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts]
    files.append(HERE / "grade.py")
    return {str(p.relative_to(HERE)): _h(p) for p in files}


def build() -> dict:
    tasks = sorted(p.name for p in (HERE / "tasks").iterdir() if p.is_dir())
    rng = random.Random(SEED)
    order = {}
    for t in tasks:
        arms = ["A", "B"]
        rng.shuffle(arms)
        order[t] = arms
    return {
        "study": "abc-v1",
        "schema": 1,
        "seed": SEED,
        "status": "PREREGISTERED_FROZEN_BEFORE_ANY_LIVE_RUN",
        "arms": ARMS,
        "tasks": {t: json.loads((HERE / "tasks" / t / "task.json").read_text()) for t in tasks},
        "task_clusters": sorted({json.loads((HERE / "tasks" / t / "task.json").read_text())["cluster"] for t in tasks}),
        "run_order_counterbalanced_seeded": order,
        "primary_endpoint": "CORRECT = visible AND hidden tests pass on the candidate files actually produced "
                            "(only task.write_paths are honoured; other changes are ignored and reported)",
        "outcomes": ["CORRECT", "FALSE_GREEN", "FAIL", "INCONCLUSIVE", "NOT_RUN", "ABSTAIN"],
        "secondary_endpoints": ["false_green_count", "wall_seconds", "observed_usd", "agent_count",
                                "abstentions", "human_interventions", "attempted_but_failed_runs"],
        "caps": {"total_usd": 150, "per_call_usd": 10, "note": "includes all prior spend; UNKNOWN cost is not 0"},
        "analysis": "n=4 tasks (2 Python, 2 Node clusters). Descriptive counts only; no significance or "
                    "superiority claim. Verdict stays NOT_YET_DEMONSTRATED unless matched live arms exist "
                    "and are reported with their uncertainty.",
        "hidden_grader_policy": "hidden/ is never copied into the agent workspace nor mentioned in prompts; "
                                "grading happens in a separate temp copy.",
        "negative_controls": "each task ships a `decoy` that passes visible tests and must grade FALSE_GREEN, "
                             "and the untouched `repo` that must grade FAIL.",
        "sha256": digests(),
    }


if __name__ == "__main__":
    mf = HERE / "manifest.json"
    if sys.argv[1:] == ["write"]:
        mf.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n")
        print("wrote", mf)
    elif sys.argv[1:] == ["verify"]:
        want = json.loads(mf.read_text())["sha256"]
        got = digests()
        bad = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
        print("OK" if not bad else f"MISMATCH {bad}")
        sys.exit(1 if bad else 0)
    else:
        sys.exit("usage: make_manifest.py write|verify")
