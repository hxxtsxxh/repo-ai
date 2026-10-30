"""Versioned evaluation protocol and preregistered study specification for the Reality Engine.

Separates:
1. `deterministic_harness_integrity_check`: zero-cost local execution that empirically runs
   a single-test smoke runner for the naive baseline and grades both arms against held-out
   `independent_grader_tests` unseen during candidate selection, plus verifies negative-control
   abstention when all candidate patches are defective.
2. `preregistered_study_protocol`: multi-arm + ablation study protocol across unseen
   repository-disjoint task clusters with seeded randomization, Wilson 95% CIs, and honest
   `NOT_YET_DEMONSTRATED` comparative lift verdict until paired live provider trials are run.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .diagnosis import diagnose
from .explanation import explain
from .runtime import git, handoff, plan, status, verify_handoff
from .tournament import compare_candidates

PROTOCOL_VERSION = "repo-ai.reality-eval/1"


def wilson_ci_95(successes: int, total: int) -> tuple[float, float]:
    """Compute 95% Wilson score confidence interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    phat = successes / total
    denom = 1.0 + (z * z) / total
    center = (phat + (z * z) / (2.0 * total)) / denom
    half = (z * math.sqrt((phat * (1.0 - phat) + (z * z) / (4.0 * total)) / total)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _setup_python_retry_fixture(root: Path) -> dict[str, Any]:
    repo = root / "py_retry"
    repo.mkdir(parents=True)
    source = "charge.py"
    original = "def charge(amount, retries):\n    return amount * (retries + 1)\n"
    superficial = "def charge(amount, retries):\n    return 10\n"
    correct = "def charge(amount, retries):\n    return amount\n"
    tests = (
        "from charge import charge\n\n"
        "def test_retry():\n    assert charge(10, 2) == 10\n\n"
        "def test_once():\n    assert charge(10, 0) == 10\n\n"
        "def test_other_amount():\n    assert charge(7, 2) == 7\n"
    )
    independent_grader_tests = (
        "from charge import charge\n\n"
        "def test_heldout_zero():\n    assert charge(0, 5) == 0\n\n"
        "def test_heldout_large():\n    assert charge(250, 1) == 250\n\n"
        "def test_heldout_high_retry():\n    assert charge(19, 99) == 19\n"
    )
    (repo / source).write_text(original, encoding="utf-8")
    (repo / "test_charge.py").write_text(tests, encoding="utf-8")
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n', encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixture baseline")
    return {
        "name": "python-duplicate-charge",
        "repo": repo,
        "source": source,
        "command": "python -m pytest",
        "smoke_test_filter": "test_retry",
        "original": original,
        "superficial": superficial,
        "correct": correct,
        "independent_grader_tests": independent_grader_tests,
    }


def _setup_python_discount_fixture(root: Path) -> dict[str, Any]:
    repo = root / "py_discount"
    repo.mkdir(parents=True)
    source = "discount.py"
    original = "def apply_discount(price, pct):\n    return price - price * pct\n"
    superficial = "def apply_discount(price, pct):\n    return 80\n"
    correct = "def apply_discount(price, pct):\n    return price - (price * pct) // 100\n"
    tests = (
        "from discount import apply_discount\n\n"
        "def test_twenty_percent():\n    assert apply_discount(100, 20) == 80\n\n"
        "def test_zero_percent():\n    assert apply_discount(50, 0) == 50\n\n"
        "def test_fifty_percent():\n    assert apply_discount(200, 50) == 100\n"
    )
    independent_grader_tests = (
        "from discount import apply_discount\n\n"
        "def test_heldout_fifteen_percent():\n    assert apply_discount(300, 15) == 255\n\n"
        "def test_heldout_full_discount():\n    assert apply_discount(99, 100) == 0\n\n"
        "def test_heldout_quarter():\n    assert apply_discount(40, 25) == 30\n"
    )
    (repo / source).write_text(original, encoding="utf-8")
    (repo / "test_discount.py").write_text(tests, encoding="utf-8")
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n', encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "discount fixture baseline")
    return {
        "name": "python-integer-discount",
        "repo": repo,
        "source": source,
        "command": "python -m pytest",
        "smoke_test_filter": "test_twenty_percent",
        "original": original,
        "superficial": superficial,
        "correct": correct,
        "independent_grader_tests": independent_grader_tests,
    }


def _write_replay(path: Path, source: str, original: str, after: str, label: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "repo-ai.replay/1",
                "label": label,
                "edits": [
                    {
                        "path": source,
                        "before_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                        "after": after,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_independent_grader(
    repo: Path,
    source: str,
    candidate_source_text: str,
    independent_grader_tests: str,
) -> dict[str, Any]:
    """Run held-out independent grader tests in a clean scratch copy unseen by tournament selection."""
    with tempfile.TemporaryDirectory(prefix="repo-ai-heldout-grader-") as tmp:
        grader_dir = Path(tmp) / "work"
        shutil.copytree(repo, grader_dir)
        (grader_dir / source).write_text(candidate_source_text, encoding="utf-8")
        heldout_file = grader_dir / "test_independent_heldout.py"
        heldout_file.write_text(independent_grader_tests, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(heldout_file.name)],
            cwd=grader_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
        }


def _selected_candidate_source(repo: Path, mission: str, source: str) -> str:
    """Materialize the recorded winning patch, never the fixture's answer key."""
    state = status(repo, mission)
    patch = state.get("diff", "")
    if (state.get("effective_verdict") != "PASS" or state.get("freshness") != "fresh"
            or not patch or hashlib.sha256(patch.encode()).hexdigest() != state.get("diff_sha256")):
        raise ValueError("selected candidate evidence or patch integrity is invalid")
    with tempfile.TemporaryDirectory(prefix="repo-ai-eval-selected-") as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(repo, work)
        patch_path = Path(tmp) / "candidate.patch"
        patch_path.write_text(patch + ("\n" if not patch.endswith("\n") else ""), encoding="utf-8")
        git(work, "apply", "--check", str(patch_path))
        git(work, "apply", str(patch_path))
        return (work / source).read_text(encoding="utf-8")


def _run_naive_smoke_trial(fx: dict[str, Any]) -> dict[str, Any]:
    """Empirically execute Arm A: direct in-place write + single smoke assertion + held-out grading."""
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="repo-ai-naive-arm-") as tmp:
        naive_repo = Path(tmp) / "repo"
        shutil.copytree(fx["repo"], naive_repo)
        source_path = naive_repo / fx["source"]
        source_path.write_text(fx["superficial"], encoding="utf-8")
        smoke_proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-k", fx["smoke_test_filter"]],
            cwd=naive_repo,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        smoke_passed = smoke_proc.returncode == 0
        # Writing the requested source is the treatment, not a side effect.
        changed = set(git(naive_repo, "diff", "--name-only", "-z").split("\0")) - {""}
        untracked = set(git(naive_repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")) - {""}
        artifacts = {p for p in untracked if "__pycache__" in Path(p).parts
                     or ".pytest_cache" in Path(p).parts}
        unscoped_touch = bool((changed | (untracked - artifacts)) - {fx["source"]})
        heldout = _run_independent_grader(
            fx["repo"],
            fx["source"],
            source_path.read_text(encoding="utf-8"),
            fx["independent_grader_tests"],
        )
        elapsed = round(time.monotonic() - t0, 4)
        verified_completion = smoke_passed and heldout["passed"] and not unscoped_touch
        false_pass = smoke_passed and not heldout["passed"]
        regression_escape = not heldout["passed"]
        return {
            "task": fx["name"],
            "smoke_test_passed": smoke_passed,
            "independent_grader_passed": heldout["passed"],
            "verified_completion": verified_completion,
            "false_pass": false_pass,
            "unscoped_file_touch": unscoped_touch,
            "regression_escape": regression_escape,
            "seconds": elapsed,
            "cost_usd": 0.0,
        }


def build_preregistered_study_spec(seed: int = 20261027) -> dict[str, Any]:
    """Return a draft protocol; registration requires an immutable task manifest."""
    rng = random.Random(seed)
    primary_arms = [
        "single_agent_unassisted",
        "single_agent_repo_ai",
        "repo_ai_adaptive_delegation",
    ]
    ablation_arms = [
        "no_retrieval",
        "no_ledger_invalidation",
        "no_tournament",
        "no_skill_broker",
    ]
    clusters = [
        "python_stateful_finance",
        "python_concurrency_retry",
        "node_cjs_protocol_parsers",
        "negative_control_defective_candidates",
    ]
    schedule = [(c, a) for c in clusters for a in primary_arms]
    rng.shuffle(schedule)
    return {
        "schema": "repo-ai.preregistered-study/1",
        "registration_status": "DRAFT_REQUIRES_FROZEN_TASK_MANIFEST",
        "live_runs_authorized": False,
        "primary_endpoint": "paired_independently_verified_completion",
        "minimum_repository_clusters": {"python": 2, "node_or_typescript": 2},
        "freeze_requirements": [
            "Repository-disjoint task IDs, source commits, oracle hashes and exclusion rules before any held-out run",
            "Same provider/model/runtime, permission scope, budget, deadlines and source disclosure for A/B; C separately justified",
            "Full counterbalanced within-task arm order; no adaptive task rewriting after results",
            "Independent grader identity and hidden-oracle isolation; objective completion and false-assurance definitions",
            "Paired task-level differences and repository-cluster uncertainty; report n and discordant pairs, no claim from two demos",
            "Record elapsed time, observed USD or UNKNOWN, tokens, interventions, agents, retries, cleanup and recovery outcomes",
            "Explicit owner authorization for named provider, disclosed source, quota and enforceable spend ceiling",
        ],
        "comparative_lift_verdict": "NOT_YET_DEMONSTRATED",
        "randomization_seed": seed,
        "primary_arms": primary_arms,
        "ablation_arms": ablation_arms,
        "task_clusters": clusters,
        "randomized_block_schedule_preview": [{"cluster": c, "arm": a} for c, a in schedule[:6]],
        "target_thresholds": {
            "relative_verified_success_improvement_min": 0.10,
            "median_time_or_cost_reduction_min": 0.25,
            "status": "aspirational_research_target_not_established_fact",
        },
        "grading_rules": [
            "Held-out independent_grader_tests are never visible in the agent workspace during candidate generation or selection",
            "Matched provider binary version, prompt context disclosure, wall-clock timeout, and USD budget ceiling across arms",
            "Negative-control defective tasks require intentional abstention (INCONCLUSIVE / winner=None); accepting any patch counts as a false assurance",
        ],
    }


def run_evaluation_protocol(directory: Path | None = None) -> dict[str, Any]:
    """Run paired deterministic harness integrity checks comparing naive smoke baseline vs Reality Engine."""
    with tempfile.TemporaryDirectory(prefix="repo-ai-reality-eval-") as tmp:
        work = directory.resolve() if directory is not None else Path(tmp).resolve()
        work.mkdir(parents=True, exist_ok=True)
        fixtures = [
            _setup_python_retry_fixture(work),
            _setup_python_discount_fixture(work),
        ]

        naive_rows: list[dict[str, Any]] = []
        engine_rows: list[dict[str, Any]] = []

        for fx in fixtures:
            repo: Path = fx["repo"]
            source: str = fx["source"]
            original: str = fx["original"]

            # Arm A: empirically run single-test smoke check + held-out independent grader
            naive_rows.append(_run_naive_smoke_trial(fx))

            # Arm B: Reality Engine verified tournament + diagnosis + handoff + held-out independent grader
            t1 = time.monotonic()
            planned = plan(
                repo,
                f"Repair {source} without regressions",
                agent="replay",
                write_paths=[source],
                execute_local=True,
                command=fx["command"],
            )
            bad_prop = _write_replay(
                work / f"{fx['name']}-superficial.json",
                source,
                original,
                fx["superficial"],
                "superficial candidate",
            )
            good_prop = _write_replay(
                work / f"{fx['name']}-correct.json",
                source,
                original,
                fx["correct"],
                "verified candidate",
            )
            comp = compare_candidates(repo, planned, [bad_prop, good_prop])
            winner_id = comp["winner"]
            assert winner_id is not None
            diag = diagnose(repo, winner_id)
            exp = explain(repo, winner_id)
            cap = handoff(repo, winner_id, target_provider="claude")
            vcap = verify_handoff(repo, cap)
            selected_source = _selected_candidate_source(repo, winner_id, source)
            heldout = _run_independent_grader(repo, source, selected_source, fx["independent_grader_tests"])
            elapsed = round(time.monotonic() - t1, 3)
            source_untouched = (repo / source).read_text(encoding="utf-8") == original
            tournament_passed = comp["verdict"] == "PASS" and diag["standing"] == "OBSERVED" and exp["verdict"] == "PASS"
            engine_rows.append({
                "task": fx["name"],
                "comparison_id": comp["id"],
                "winner_mission": winner_id,
                "superficial_rejected": comp["candidates"][0]["verdict"] == "FAIL",
                "independent_grader_passed": heldout["passed"],
                "verified_completion": tournament_passed and heldout["passed"],
                "false_pass": tournament_passed and not heldout["passed"],
                "unscoped_file_touch": not source_untouched,
                "regression_escape": tournament_passed and not heldout["passed"],
                "handoff_verified": vcap["valid"],
                "context_tokens_overhead": planned["context"]["limits"]["budget_tokens_estimate"],
                "seconds": elapsed,
                "cost_usd": 0.0,
            })

        # Negative-control abstention check: both candidates are defective; tournament must abstain
        neg_fx = fixtures[0]
        defective_b = _write_replay(
            work / "neg-defective-b.json",
            neg_fx["source"],
            neg_fx["original"],
            "def charge(amount, retries):\n    return amount + retries + 1\n",
            "second defective candidate",
        )
        neg_planned = plan(
            neg_fx["repo"],
            "Negative control: both candidates defective",
            agent="replay",
            write_paths=[neg_fx["source"]],
            execute_local=True,
            command=neg_fx["command"],
        )
        neg_comp = compare_candidates(
            neg_fx["repo"],
            neg_planned,
            [work / f"{neg_fx['name']}-superficial.json", defective_b],
        )
        negative_control_abstained = neg_comp["winner"] is None and neg_comp["verdict"] == "INCONCLUSIVE"

        n_tasks = len(fixtures)
        naive_succ = sum(1 for r in naive_rows if r["verified_completion"])
        engine_succ = sum(1 for r in engine_rows if r["verified_completion"])

        report = {
            "schema": PROTOCOL_VERSION,
            "mode": "deterministic_harness_integrity_check",
            "live_model_claims": False,
            "comparative_lift_verdict": "NOT_YET_DEMONSTRATED",
            "independent_heldout_grader": True,
            "negative_control_abstention_verified": negative_control_abstained,
            "tasks_evaluated": n_tasks,
            "arms": {
                "unassisted_naive_baseline": {
                    "verified_completion_rate": round(naive_succ / n_tasks, 3),
                    "verified_completion_wilson_95_ci": list(wilson_ci_95(naive_succ, n_tasks)),
                    "false_pass_rate": round(sum(r["false_pass"] for r in naive_rows) / n_tasks, 3),
                    "median_seconds_to_verified_change": None,
                    "human_interventions": n_tasks,
                    "cost_usd": 0.0,
                    "context_tokens_overhead": 0,
                    "unscoped_file_touch_rate": round(sum(r["unscoped_file_touch"] for r in naive_rows) / n_tasks, 3),
                    "regression_escape_rate": round(sum(r["regression_escape"] for r in naive_rows) / n_tasks, 3),
                    "handoff_recovery_success_rate": 0.0,
                    "tasks": naive_rows,
                },
                "reality_engine_verified": {
                    "verified_completion_rate": round(engine_succ / n_tasks, 3),
                    "verified_completion_wilson_95_ci": list(wilson_ci_95(engine_succ, n_tasks)),
                    "false_pass_rate": round(sum(r["false_pass"] for r in engine_rows) / n_tasks, 3),
                    "median_seconds_to_verified_change": round(statistics.median(r["seconds"] for r in engine_rows), 3),
                    "human_interventions": 0,
                    "cost_usd": 0.0,
                    "context_tokens_overhead": round(statistics.mean(r["context_tokens_overhead"] for r in engine_rows), 1),
                    "unscoped_file_touch_rate": round(sum(r["unscoped_file_touch"] for r in engine_rows) / n_tasks, 3),
                    "regression_escape_rate": round(sum(r["regression_escape"] for r in engine_rows) / n_tasks, 3),
                    "handoff_recovery_success_rate": round(sum(r["handoff_verified"] for r in engine_rows) / n_tasks, 3),
                    "tasks": engine_rows,
                },
            },
            "preregistered_study_protocol": build_preregistered_study_spec(),
            "limitations": [
                "Deterministic harness integrity check; empirically executes smoke vs full suite and held-out independent grader at $0 model cost",
                "Does not claim live LLM product lift (comparative_lift_verdict=NOT_YET_DEMONSTRATED); live multi-arm efficacy requires running preregistered_study_protocol across unseen task clusters",
            ],
        }
        if directory is not None:
            (work / "eval-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
