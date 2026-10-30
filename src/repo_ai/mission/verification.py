"""Strict, isolated observations for a mission; not a proof of correctness.

The caller authorizes execution. This module never edits the source, publishes
verify/gate evidence, or runs repository tests on the host. Reports are still
produced by the program under test; local evidence is not a security certificate.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

from .. import __version__, sandbox
from ..security import redact_text
from ..verify import cache, changes, engine, evidence, execute, isolate, results
from ..verify.runner import TestRunner, parse_command

SCHEMA = "repo-ai.mission-observation/1"
_REPORT = "mission-observation"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runner(command: str) -> TestRunner:
    runner = parse_command(command)
    if runner.kind not in {"pytest", "node"} or not results.can_instrument(runner, runner.full):
        raise ValueError("P0 requires an instrumentable pytest or node --test command")
    # Deliberately small initial surface: no selectors, alternative configuration,
    # collection-only, parallel pytest plugins or reporter overrides.
    args = runner.full[3:] if runner.kind == "pytest" else runner.full[1:]
    allowed = {"--disable-warnings", "--no-header", "--no-summary",
               "--tb=short", "--tb=line", "--tb=long", "--tb=no"}
    if runner.paths or any(not (a == "--test" if runner.kind == "node" else
                               a in allowed or re.fullmatch(r"-[qv]+", a)) for a in args):
        raise ValueError("P0 requires full discovery without test paths, filters or configuration overrides")
    return runner


def test_support(path: str) -> bool:
    """Conservative frozen acceptance boundary, including non-entrypoint helpers.

    Arbitrary helpers outside conventional test trees are not statically resolved.
    This boundary is not a claim of semantic independence from production code.
    """
    lowered = Path(path.lower())
    lower_config = {c.lower() for c in engine.COLLECTION_CONFIG}
    lower_deps = {d.lower() for d in engine.DEPENDENCY_NAMES}
    support_dirs = {
        'test', 'tests', '__tests__', 'testing', 'fixtures', '__fixtures__',
        'spec', 'specs', 'test_helpers', 'testutils', '__mocks__', 'mocks',
    }
    return (bool(support_dirs & set(lowered.parts[:-1]))
            or lowered.name in lower_config
            or lowered.name in lower_deps
            or lowered.name in {'conftest.py', 'setup.py', 'sitecustomize.py', 'usercustomize.py', 'tsconfig.json'})


def _test_inputs(root: Path, files: list[str], universe: list[str]) -> dict[str, str]:
    # Same IDs with edited assertions/configuration are not the same experiment.
    pinned = set(universe) | {f for f in files if test_support(f)}
    out = {}
    for rel in sorted(pinned):
        data = isolate.read_inside(root, rel, results.MAX_REPORT_BYTES)
        if data is None:
            raise ValueError(f"test input is not a readable regular file: {rel}")
        out[rel] = _hash(data)
    return out


def _outcomes(report: Path, runner: TestRunner, files: list[str], inside: str,
              att: results.Attribution) -> tuple[dict[str, str], list[str]]:
    # Use the existing bounded, no-symlink reader and the same attribution mapper
    # as results.parse; do not add an unsafe second JSON reader for mission data.
    events, problem = results._events(report)
    reasons = [problem] if problem else []
    mapper = results._Mapper(runner, files, inside)
    outcomes: dict[str, str] = {}
    for event in events:
        if event.get("e") != "end":
            continue
        outcome = event.get("o")
        # A skipped *test* is recorded and must be skipped identically at base and candidate (`comparability`);
        # a skipped file or suite hides which tests it holds, and xfail inverts the outcome: both stay refused.
        if (outcome == "skip" and any(event.get(k) is True for k in ("suite", "collect"))) \
                or event.get("xfail") is True:
            reasons.append("a test suite was skipped, or a test was expected to fail")
        if event.get("collect") is True:
            reasons.append("test collection did not complete normally")
        if outcome == "skip" and event.get("file") is True and not event.get("collect"):
            # a file skipped as a whole is one recorded entry, held to the same base == candidate rule as a test
            whole = mapper.file(event)
            if whole:
                outcomes[f"{whole}::<module skipped>"] = "skip"
            else:
                reasons.append("a skipped test file has no unambiguous identity")
            continue
        if any(event.get(k) is True for k in ("file", "suite", "collect", "sub")):
            continue
        file, tid = mapper.file(event), event.get("id")
        if not file or not isinstance(tid, str) or not tid or len(tid) > 1000:
            reasons.append("a test outcome has no unambiguous file and test identity")
            continue
        if outcome not in {"pass", "fail", "error", "skip"}:
            reasons.append("a test outcome is malformed")
            continue
        key = f"{file}::{tid}"
        if key in outcomes:
            reasons.append("duplicate test identity in the report")
        outcomes[key] = outcome
        if outcome == "error":
            reasons.append("a test errored during setup or teardown rather than demonstrating a failing assertion")
    if not outcomes:
        reasons.append("no actual test outcomes were reported")
    elif all(o == "skip" for o in outcomes.values()):
        reasons.append("every test was skipped")
    if runner.kind == "pytest":
        if not att.collected or any(not att.complete(f) for f in att.collected):
            reasons.append("not every collected test completed")
        if not set(files) <= att.modules:
            reasons.append("not every discovered test file was collected")
    elif not set(files) <= att.finished:
        reasons.append("not every discovered node test file completed")
    if sum(f.tests for f in att.files.values()) != len(outcomes):
        reasons.append("reported test counts disagree with unique test outcomes")
    if any(tid == "<file>" for f in att.files.values() for tid in f.failing):
        reasons.append("the test process failed outside an actual test")
    return outcomes, list(dict.fromkeys(reasons))


def observe(root: Path, command: str, timeout_s: float = 60,
            sandbox_preference: str = "auto") -> dict:
    """Run one fresh, complete suite in a disposable, network-denied sandbox.

    Invalid input, unavailable environments and incomplete execution produce an
    ineligible observation with reasons. KeyboardInterrupt propagates after the
    workspace context cleans up; callers retain the existing signal handling.
    Output hashes identify captured output, which the sandbox bounds in size.
    """
    observation: dict[str, Any] = {
        "schema": SCHEMA, "repo_ai_version": __version__, "trusted": False, "complete": False,
        "test_ids": [], "outcomes": {}, "ran": 0, "failed": 0, "skipped": 0,
        "reasons": [], "environment_static": None, "environment_key": "",
        "environment_unchanged": False, "executor": {}, "pin": {},
        "integrity": {"unchanged": False}, "cleanup_confirmed": False,
        "exit_code": None, "timed_out": False, "stdout_sha256": None, "stderr_sha256": None,
    }
    reasons = observation["reasons"]
    before = None
    workspace_path = None
    try:
        if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout must be positive and finite")
        root = root.resolve(strict=True)
        runner = _runner(command)
        listing = isolate.worktree_files(root)
        files = runner.test_files(listing[0], root)
        if not files:
            raise ValueError("no supported test files were discovered")
        head = changes.resolve_base(root, "HEAD")
        fingerprint = changes.fingerprint(root, "HEAD")
        before = isolate.snapshot(root, listing[0], skip=engine._own_state(root, None))
        observation["pin"] = {"head": head, "fingerprint": fingerprint, "command": command,
                              "runner": cache.runner_identity(runner),
                              "test_inputs": _test_inputs(root, listing[0], files)}
        executor = execute.get_executor(root, sandbox_preference, runner.language, timeout_s=timeout_s)
        identity = {"backend": executor.backend.name, "language": runner.language,
                    "interpreter": executor.node if runner.kind == "node" else executor.python,
                    "network": False}
        if executor.is_container:
            assert isinstance(executor.backend, sandbox.ContainerBackend)
            digest = executor.backend.image_digest(runner.language)
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("container image lacks an immutable identity")
            ref = executor.backend.images[runner.language]
            pinned = digest if executor.backend.name == "docker" else ref.partition("@")[0] + "@" + digest
            executor.backend.images = {**executor.backend.images, runner.language: pinned}
            identity.update(image=pinned, image_digest=digest)
        observation["executor"] = identity
        with isolate.materialize(root, label="mission-observe", listing=listing) as ws:
            workspace_path = ws.path
            if changes.fingerprint(root, "HEAD") != fingerprint:
                raise ValueError("source changed while preparing the observation")
            bound = executor.in_workspace(ws)
            static = cache.static_environment(bound, runner)
            environment = cache.environment_key(bound, runner)
            observation.update(environment_static=static, environment_key=environment, isolation=ws.summary())
            argv, report = results.instrument(runner, runner.full, ws.path, bound.inside_root, _REPORT, native=True)
            result = bound.run(argv, cwd=runner.cwd, env=runner.env, timeout_s=timeout_s, toolchain=runner.language)
            observation.update(exit_code=result.exit_code, timed_out=result.timed_out, seconds=result.duration_s,
                               stdout_sha256=_hash(result.stdout.encode("utf-8", "replace")),
                               stderr_sha256=_hash(result.stderr.encode("utf-8", "replace")))
            att = results.parse(report, runner, files, bound.inside_root,
                                exit_code=result.exit_code, timed_out=result.timed_out)
            outcomes, report_problems = _outcomes(report, runner, files, bound.inside_root, att)
            reasons.extend(report_problems)
            if not att.trusted:
                reasons.append(att.reason or "untrusted test report")
            if result.timed_out or not att.done or att.stopped:
                reasons.append("test execution did not finish completely")
            if result.notes:
                reasons.extend(redact_text(evidence.scrub(n, 500)) for n in result.notes)
            unchanged = (cache.static_environment(bound, runner) == static
                         and cache.environment_key(bound, runner) == environment)
            observation.update(outcomes=outcomes, test_ids=sorted(outcomes),
                               ran=sum(o != "skip" for o in outcomes.values()),
                               failed=sum(o in {"fail", "error"} for o in outcomes.values()),
                               skipped=sum(o == "skip" for o in outcomes.values()),
                               environment_unchanged=unchanged, trusted=att.trusted)
            if not unchanged:
                reasons.append("test environment changed during the observation")
    except (OSError, ValueError, RuntimeError) as exc:
        reasons.append(redact_text(evidence.scrub(str(exc), 500)))
    finally:
        if before is not None:
            try:
                after = isolate.snapshot(root, list(before.content), skip=before.skip)
                changed = before.changes(after)
                pin = observation["pin"]
                if changes.resolve_base(root, "HEAD") != pin.get("head"):
                    changed.append("HEAD changed")
                if changes.fingerprint(root, "HEAD") != pin.get("fingerprint"):
                    changed.append("working-tree fingerprint changed")
                observation["integrity"] = {"unchanged": not changed, "changes": changed[:50]}
                if changed:
                    reasons.append("source tree changed during observation")
            except (OSError, ValueError, RuntimeError) as exc:
                reasons.append("source integrity could not be checked: " + redact_text(evidence.scrub(str(exc), 500)))
        cleanup = sandbox.cleanup_problems()
        left_workspace = workspace_path is not None and workspace_path.exists()
        observation["cleanup_confirmed"] = not cleanup and not left_workspace
        if left_workspace:
            reasons.append("disposable observation workspace cleanup was not confirmed")
        if cleanup:
            reasons.append("sandbox process cleanup could not be confirmed")
    observation["reasons"] = list(dict.fromkeys(reasons))
    observation["complete"] = bool(observation["trusted"] and not reasons
                                   and observation["environment_unchanged"] and observation["integrity"]["unchanged"])
    return observation


def _problems(record: object, label: str) -> list[str]:
    if not isinstance(record, dict):
        return [f"{label}: observation is missing or malformed"]
    problems = []
    if record.get("schema") != SCHEMA or record.get("repo_ai_version") != __version__:
        problems.append("unknown observation schema or tool version")
    if any(record.get(k) is not True for k in ("trusted", "complete", "environment_unchanged", "cleanup_confirmed")):
        problems.append("observation is untrusted, incomplete, environmentally unstable or not cleaned up")
    if not isinstance(record.get("integrity"), dict) or record["integrity"].get("unchanged") is not True:
        problems.append("source integrity is unconfirmed")
    outcomes, ids = record.get("outcomes"), record.get("test_ids")
    if (not isinstance(outcomes, dict) or not outcomes or not isinstance(ids, list)
            or not all(isinstance(i, str) and i for i in ids) or len(ids) != len(set(ids))
            or set(ids) != set(outcomes) or any(o not in {"pass", "fail", "skip"} for o in outcomes.values())
            or all(o == "skip" for o in outcomes.values())):
        problems.append("nonempty, unique, real pass/fail test outcomes are required")
    else:
        expected = {"ran": sum(o != "skip" for o in outcomes.values()),
                    "failed": sum(o == "fail" for o in outcomes.values()),
                    "skipped": sum(o == "skip" for o in outcomes.values())}
        if any(type(record.get(k)) is not int or record[k] != v for k, v in expected.items()):
            problems.append("test counts do not agree with outcomes")
    expected_exit = 1 if record.get("failed", 0) else 0
    if type(record.get("exit_code")) is not int or record["exit_code"] != expected_exit \
            or record.get("timed_out") is not False:
        problems.append("exit status or timeout contradicts the reported outcomes")
    for key in ("stdout_sha256", "stderr_sha256"):
        if not isinstance(record.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", record[key]):
            problems.append("captured output integrity is missing")
    pin = record.get("pin")
    if not isinstance(pin, dict) or not pin.get("fingerprint") or not pin.get("test_inputs") or not pin.get("runner"):
        problems.append("test inputs or source identity were not pinned")
    if not isinstance(record.get("executor"), dict) or not record["executor"] or not record.get("environment_key"):
        problems.append("executor or environment identity is missing")
    if cache.static_environment_change(record.get("environment_static"))[0] != "unchanged":
        problems.append("recorded environment is missing or stale")
    return [f"{label}: {reason}" for reason in problems]


def comparability(baseline: dict, candidate: dict) -> list[str]:
    """Validate an experiment independently of whether either candidate passes."""
    reasons = _problems(baseline, "baseline") + _problems(candidate, "candidate")
    if reasons:
        return reasons
    for key in ("test_ids", "environment_static", "environment_key", "executor", "repo_ai_version"):
        if baseline[key] != candidate[key]:
            reasons.append(f"baseline and candidate have different {key}")
    for key in ("command", "runner", "test_inputs"):
        if baseline["pin"].get(key) != candidate["pin"].get(key):
            reasons.append(f"baseline and candidate have different pinned {key}")
    skipped = {side: {t for t, o in record["outcomes"].items() if o == "skip"}
               for side, record in (("baseline", baseline), ("candidate", candidate))}
    if skipped["baseline"] != skipped["candidate"]:
        # a candidate must not make a test skip (or un-skip one) to change the verdict
        reasons.append("baseline and candidate skip different tests")
    return reasons


def compare(baseline: dict, candidate: dict) -> tuple[str, list[str]]:
    """PASS means the identical observed suite failed then passed, not correctness.

    Both observations must be fresh and eligible. Test/config bytes, command,
    runtime and backend stay fixed; source fingerprints may differ by design.
    """
    reasons = comparability(baseline, candidate)
    if reasons:
        return "FAIL", reasons
    if baseline["failed"] < 1:
        reasons.append("baseline did not demonstrate a real failing test")
    if candidate["failed"] or any(o not in {"pass", "skip"} for o in candidate["outcomes"].values()):
        reasons.append("candidate did not pass every test")
    return ("FAIL", reasons) if reasons else ("PASS", [])
