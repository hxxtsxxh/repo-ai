"""Verification evidence: what was run for which exact change, and what
happened. Stored locally under the repository's repo-ai state directory
(never committed, never sent anywhere).

A record is tied to the change fingerprint (base commit plus the content of
every changed file), so "verified" can be checked mechanically: evidence for
a different working tree is reported as stale, not as a pass.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import __version__

SCHEMA = "repo-ai.verify-evidence/1"
_SECRETISH = re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)(\s*[:=]\s*)\S+")


def scrub(text: str, limit: int = 1500) -> str:
    """Output tails go into local evidence: keep them short and mask
    credential-looking assignments."""
    return _SECRETISH.sub(r"\1\2<redacted>", text[-limit:])


_FAIL_LINE = re.compile(
    r"^(?:(?:FAIL|ERROR): .*|FAILED .*|E +.*|\w*(?:Error|Exception)(?:: .*)?|not ok .*|✖ .*|"
    r"# fail \d+|Ran \d+ tests? in .*)$")


_UNITTEST_ID = re.compile(r"^(?:FAIL|ERROR): \S+ \(([^)]+)\)", re.M)
_PYTEST_ID = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+)", re.M)
_NODE_ID = re.compile(r"^\s*(?:not ok \d+ - (.+?)\s*$|✖ (.+?) \(\d)", re.M)


def failing_tests(text: str) -> set[str]:
    """Individual failing test ids in unittest, pytest or node:test output."""
    ids = {m.group(1) for m in _UNITTEST_ID.finditer(text)}
    ids |= {m.group(1) for m in _PYTEST_ID.finditer(text)}
    ids |= {(m.group(1) or m.group(2)).strip() for m in _NODE_ID.finditer(text)}
    return ids


def failure_excerpt(text: str, limit: int = 12) -> str:
    """The lines that say what failed (unittest, pytest, node:test), not the
    last screenful of output."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    picked = [ln for ln in lines if ln.strip() and _FAIL_LINE.match(ln.strip())]
    return scrub("\n".join(picked[:limit]) if picked else "\n".join(lines[-limit:]))


# The verdicts that mean "the change passed verification": every consumer (exit code, gate,
# integrations) uses this one definition. Anything else is not a pass.
PASSING_VERDICTS = ("selected-and-full-suite-passed", "selected-passed (full suite not run)", "nothing-selected")


def is_passing(verdict: object) -> bool:
    return str(verdict or "").startswith(PASSING_VERDICTS)


NOT_VERIFIED_UNLINKED = "not verified: no test is linked to the behavioural change (nothing was selected)"
NOT_VERIFIED_FULL_NOT_RUN = "not verified: the full suite is required for this change and could not be run"


def verdict(results: list[dict[str, Any]], full: dict[str, Any] | None, selected: int,
            full_required: bool, behavioural: bool = True, incomplete: str = "") -> str:
    """One phrase for the whole run. Anything that is not a pass is reported
    as a failure; a failure is called pre-existing only when the base run
    showed the same tests failing. `behavioural`: the change alters code
    behaviour (not only comments, formatting, documentation or repo-ai's own
    files). Nothing selected is a pass (`nothing-selected`) only when it is
    not: a behavioural change that no test ran verified nothing.
    `incomplete`: why the run could not finish (its time budget ran out). A
    new failure observed before that still is a regression; anything else is
    "not verified", never a pass. A file the budget cut (`deadline`) says
    nothing about the change by itself."""
    if incomplete:
        results = [r for r in results if not r.get("deadline")]
    failed = [r for r in results if r["status"] not in {"pass", "no-tests"}]
    new = [r for r in failed if r.get("baseline") in {"pass", "absent"} or r.get("new_failing_tests")]
    confirmed = [r for r in new if r.get("confirmed", True)]
    uncompared = [r for r in failed if r.get("baseline") not in {"pass", "absent", "fail"}]
    if confirmed:
        return "regression"  # whatever else happened, these failures are new and reproduced
    if incomplete:
        return f"not verified: {incomplete}"
    if (full is not None and full.get("status") not in {"pass", "not-run"} and not full.get("attributed")
            and not full.get("advisory")):
        return "full-suite-failed"
    if failed:
        if uncompared:
            return "failing (not compared with the base)"
        if new:
            return "failing (only next to other test files: order-dependent or flaky)"
        if any(r.get("changed_failures") for r in failed):
            # the same tests fail at the base, but differently: the change may have broken them anew
            return "failing (tests that fail at the base now fail differently)"
        return "failing (all failures pre-existing at the base)"
    unverified = [r for r in results if r.get("unverified")]
    if unverified:
        return (f"not verified: {len(unverified)} selected test file(s) skip every test or define none with this change "
                "(their tests run at the base)")
    if full is not None and full.get("status") == "pass":
        return "selected-and-full-suite-passed"
    if full is not None and full.get("status") not in {"pass", "not-run"} and not full.get("advisory"):
        return "full-suite-failed"
    if full is not None and full.get("advisory"):
        return "selected-passed; full suite failed (not required; its failures cannot be attributed)"
    if selected == 0:
        if full_required:
            return NOT_VERIFIED_FULL_NOT_RUN
        return NOT_VERIFIED_UNLINKED if behavioural else "nothing-selected"
    if results and all(r["status"] == "no-tests" for r in results):
        return "no tests ran: the selected files define none"
    return "selected-passed (full suite not run)" if not full_required else \
        "selected-passed; full suite REQUIRED but not run"


REUSE_MAX_AGE_S = 24 * 3600


def find_reusable(state_dir: Path, key: str) -> dict[str, Any] | None:
    """The newest evidence recorded under the same reuse key (same change,
    environment, test command and selection), less than a day old, whose
    source tree was unchanged. Returned marked as reused."""
    folder = state_dir / "evidence"
    now = time.time()
    for path in _history(folder)[:50]:
        try:
            if now - path.stat().st_mtime > REUSE_MAX_AGE_S:
                break
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("reuse_key") != key:
            continue
        if not (data.get("source_tree") or {}).get("unchanged") or str(data.get("verdict", "")).startswith("invalid"):
            continue
        data["reused"] = {"from": str(path.name), "created": data.get("created")}
        return data
    return None


def _write(path: Path, text: str) -> None:
    """Whole or not at all, whoever else is writing: a temporary file of its own,
    then an atomic rename (concurrent writers left torn files)."""
    from ..fsutil import atomic_write
    atomic_write(path, text)


def _history(folder: Path) -> list[Path]:
    """History records, newest first by when they were written. Names are not
    an order: older ones carry local time (a daylight-saving fall-back sorts a
    newer record first) and same-second names differ only by process id."""
    def written(p: Path) -> tuple[int, str]:
        try:
            return p.stat().st_mtime_ns, p.name
        except OSError:
            return 0, p.name
    return sorted(folder.glob("2*.json"), key=written, reverse=True)


def save(state_dir: Path, record: dict[str, Any], latest: bool = True) -> Path:
    """Keep the record in the bounded history; make it the latest unless
    `latest` is False (an invalid run must not replace valid evidence that a
    concurrent run just recorded)."""
    import os
    folder = state_dir / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + record["fingerprint"][:10] + f"-{os.getpid():07d}.json"
    path = folder / name
    text = json.dumps(record, indent=1, sort_keys=True) + "\n"
    _write(path, text)
    if latest:
        _write(folder / "latest.json", text)
    for stale in _history(folder)[50:]:  # bounded history
        try:
            stale.unlink()
        except OSError:
            pass
    return path


def set_latest(state_dir: Path, record: dict[str, Any]) -> None:
    """Make an existing record the latest (evidence reused for this change)."""
    folder = state_dir / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / "latest.json", json.dumps(record, indent=1, sort_keys=True) + "\n")


def for_fingerprint(state_dir: Path, fingerprint: str, semantic: str = "") -> dict[str, Any] | None:
    """The newest valid record of this change in the history: what a reader
    uses when `latest.json` is another session's run. `semantic` also accepts
    a record whose semantic fingerprint matches (a formatter-only rewrite), as
    the gate does for the latest record. The newest match decides, so a later
    failing run of the change is never passed over for an earlier pass."""
    folder = state_dir / "evidence"
    for path in _history(folder)[:50]:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(data, dict) and data.get("schema") == SCHEMA):
            continue
        if not (data.get("fingerprint") == fingerprint
                or (semantic and data.get("semantic_fingerprint") == semantic)):
            continue
        if (data.get("source_tree") or {}).get("unchanged") and not str(data.get("verdict", "")).startswith("invalid"):
            return data
    return None


def environment_check(rec: dict[str, Any], root: Path) -> tuple[str, str]:
    """Whether the test environment the record was made in is still the one
    installed: ("unchanged" | "changed" | "not recorded", detail). The
    fingerprint says nothing about it: after `pip install -U` or an edit
    inside site-packages, a pass of the same change no longer vouches for
    it (X13b). Static (`cache.static_environment_change`): no interpreter
    or repository code runs."""
    import shutil

    from .cache import static_environment_change
    from .execute import interpreter

    version = rec.get("repo_ai_version")
    if version != __version__:
        return "changed", f"repo-ai version changed ({version or 'not recorded'} -> {__version__})"
    recorded = rec.get("environment_static")
    status, detail = static_environment_change(recorded)
    if status != "unchanged":
        return "changed", detail
    # Container images are explicitly unchecked by this read-only command.
    # A host record must also match the interpreter a new run would select,
    # not merely the unchanged files belonging to the previous interpreter.
    assert isinstance(recorded, dict)  # validated by static_environment_change
    binary = recorded.get("interpreter")
    files = recorded["files"]
    if files:
        if not isinstance(binary, str) or not binary or binary != files[0]:
            return "changed", "the recorded host environment has an incomplete interpreter identity"
        plan = rec.get("plan")
        runner = plan.get("runner") if isinstance(plan, dict) else None
        kind = recorded.get("toolchain") or (runner.get("kind") if isinstance(runner, dict) else None)
        if not isinstance(kind, str):
            return "changed", "the recorded environment does not identify its test toolchain"
        if kind == "node":
            selected = shutil.which("node")
        elif kind in {"python", "pytest", "unittest"}:
            found = interpreter(root, probe=False)
            selected = found.python if found else None
        else:
            return "changed", "the recorded environment does not identify its test toolchain"
        if selected != binary:
            return "changed", f"the selected interpreter changed ({binary} -> {selected or 'unavailable'})"
    elif binary or recorded.get("unchecked") != ["container image"]:
        return "changed", "the recorded environment does not identify a host interpreter or container"
    return status, detail


def latest(state_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((state_dir / "evidence" / "latest.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def new_record(plan_json: dict[str, Any], backend: str, interpreter: str) -> dict[str, Any]:
    # local time with its UTC offset (ISO 8601), so a reader knows which time it is; records written
    # before 0.8 carry naive local time. Display only: history order is by write time (`_history`)
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    return {"schema": SCHEMA, "created": created, "repo_ai_version": __version__,
            "base": plan_json["base"], "fingerprint": plan_json["fingerprint"], "backend": backend,
            "interpreter": interpreter, "plan": {k: plan_json[k] for k in (
                "confidence", "full_suite_required", "triggers", "uncertainty", "runner",
                "test_files_total", "targeted_commands", "full_suite_command")},
            "selected": [s["test"] for s in plan_json["selected"]], "results": [], "full_suite": None}
