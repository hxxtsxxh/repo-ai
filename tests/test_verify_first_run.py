"""What a first-time user is told: a recording made with uncommitted edits is
never presented as the base, and the wording of plans and runs says what the
evidence is and nothing more (findings of a first-run audit of main 7e77912)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import run_cli

from test_verify_adaptive import CMD, needs_sandbox


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _project(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    root = tmp_path / "p"
    files = {"calc/__init__.py": "", "calc/core.py": "def add(a, b):\n    return a + b\n", "tests/__init__.py": "",
             **{f"tests/test_m{i}.py": ("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                        f"    def test_{i}(self):\n        self.assertEqual(add({i}, 1), {i + 1})\n")
                for i in range(2)}, **(extra or {})}
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


BROKEN = "def add(a, b):\n    return a - b\n"


@needs_sandbox
def test_a_recording_with_an_uncommitted_break_is_not_reported_as_base_failures(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BROKEN)
    rec = run_cli(root, "verify", "--record", "--test-command", CMD)
    assert rec.returncode == 0, rec.stderr
    assert "already failing" not in rec.stdout and "uncommitted changes to calc/core.py" in rec.stdout, rec.stdout
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")  # the break reverted
    plan = json.loads(run_cli(root, "verify", "--json", "--test-command", CMD).stdout)
    notes = " ".join(plan["uncertainty"])
    assert "already failed when evidence was recorded" not in notes, notes
    assert "with uncommitted changes to calc/core.py" in notes and "not the base" in notes, notes


@needs_sandbox
def test_a_recording_of_the_clean_base_still_reports_its_failures(tmp_path: Path):
    root = _project(tmp_path, {"tests/test_m9.py": "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                                   "    def test_9(self):\n        self.assertEqual(1, 2)\n"})
    rec = run_cli(root, "verify", "--record", "--test-command", CMD)
    assert "1 already failing: tests/test_m9.py" in rec.stdout, rec.stdout
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b + 0\n")
    plan = json.loads(run_cli(root, "verify", "--json", "--test-command", CMD).stdout)
    assert any("already failed when evidence was recorded: tests/test_m9.py" in u for u in plan["uncertainty"])


@needs_sandbox
def test_the_run_summary_counts_processes_once_and_qualifies_only_a_pass(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BROKEN)
    bad = run_cli(root, "verify", "--run", "--full", "--test-command", CMD).stdout
    assert bad.startswith("repo-ai verify") and "REGRESSION" in bad, bad
    assert "not proof the change is correct" not in bad, bad  # a regression needs no caveat about passes
    assert "the full suite as one process in" not in bad and "sandboxed process(es) in all (" in bad, bad
    assert "test_file_runs" not in bad and "repeated_file_runs" not in bad, bad  # counts of files, not processes
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    good = run_cli(root, "verify", "--run", "--test-command", CMD).stdout
    assert "PASSED" in good and "not proof the change is correct" in good, good


def test_a_declared_command_is_not_called_declared_twice(tmp_path: Path):
    root = _project(tmp_path, {"pyproject.toml": '[project]\nname = "calc"\nversion = "1"\n\n'
                                                 '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'})
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")
    out = run_cli(root, "verify").stdout
    assert "test command:" in out and "declared (declared" not in out, out


def test_medium_confidence_does_not_claim_import_evidence_alone():
    from repo_ai.verify.report import CONF_TEXT
    assert "import evidence only" not in CONF_TEXT["medium"] and "file names" in CONF_TEXT["medium"]


def test_nothing_selected_says_no_test_ran():
    from repo_ai.verify import report
    s = report.summarize({"verdict": "nothing-selected", "results": []})
    lines = report._outcome({"verdict": "nothing-selected", "results": []}, s, [])
    assert any("No test ran" in x for x in lines), lines


@needs_sandbox
def test_the_record_json_says_whether_its_failures_are_the_bases(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BROKEN)
    out = json.loads(run_cli(root, "verify", "--record", "--json", "--test-command", CMD).stdout)
    assert out["failures_are_base"] is False and out["uncommitted"] == ["calc/core.py"] and out["baseline_failures"]


def test_evidence_created_carries_its_utc_offset():
    """Record names are UTC and `created` was naive local time, so a reader could not tell which time
    it showed. It is now ISO 8601 with the offset, and parses back to the same instant."""
    from datetime import datetime, timezone
    from repo_ai.verify import evidence
    plan = {"base": "HEAD", "fingerprint": "f" * 64, "confidence": "high", "full_suite_required": False,
            "triggers": [], "uncertainty": [], "runner": {}, "test_files_total": 0, "targeted_commands": [],
            "full_suite_command": "", "selected": []}
    before = datetime.now(timezone.utc).replace(microsecond=0)
    created = datetime.fromisoformat(evidence.new_record(plan, "seatbelt", "python")["created"])
    assert created.tzinfo is not None and created.utcoffset() is not None
    assert abs((created - before).total_seconds()) < 5


@needs_sandbox
def test_a_full_run_reports_the_suites_test_counts_not_only_selected_files(tmp_path: Path):
    """Found on python-humanize: with no test file selected, a full suite of 738 passing tests printed "0 passed"."""
    root = _project(tmp_path)
    (root / "NOTES.txt").write_text("a change that selects no test file\n")
    out = run_cli(root, "verify", "--run", "--full", "--test-command", CMD).stdout
    assert "0 selected test file(s) passed" in out, out
    assert "\n  0 passed" not in out, out
    assert "full suite (" not in out, out  # unittest prints no pytest summary; counts are never derived


@pytest.mark.parametrize("stdout, expected", [
    ("....\n=== 1 failed, 738 passed, 112 skipped in 0.83s ===\n", {"failed": 1, "passed": 738, "skipped": 112}),
    ("\x1b[32m6 passed\x1b[0m in 0.02s\n", {"passed": 6}),
    ("== 2 passed, 1 error in 1.00s ==", {"passed": 2, "error": 1}),
    ("= 4 passed, 2 failed, 1 xfailed, 1 xpassed, 3 warnings in 2.01s (0:00:02) =",
     {"passed": 4, "failed": 2, "xfailed": 1, "xpassed": 1, "warnings": 3}),
    ("no summary here\n", None),
    ("= 2 failed, 1 passed, 2 subtests passed in 0.1s =", {"failed": 2, "passed": 1, "subtests passed": 2}),
    ("== 3 passed in 0.1s ==\nextra trailing output\n", {"passed": 3}),
])
def test_pytest_summary_is_quoted_not_derived(stdout, expected):
    from repo_ai.verify.engine import pytest_summary
    assert pytest_summary(stdout) == expected


@needs_sandbox
def test_a_summary_line_printed_by_the_tests_themselves_is_not_quoted(tmp_path: Path):
    """Test code can print a line that looks like pytest's summary (atexit, a plugin): it is quoted only when it agrees
    with repo-ai's per-test report, and it never decides a verdict."""
    root = _project(tmp_path, {"conftest.py": "import atexit\natexit.register(lambda: print('===== 500 passed in 0.10s ====='))\n",
                               "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'})
    (root / "calc" / "core.py").write_text(BROKEN)
    out = run_cli(root, "verify", "--run", "--full", "--test-command", "python -m pytest").stdout
    assert "REGRESSION" in out and "as pytest printed it" not in out, out


@needs_sandbox
def test_show_fixed_names_the_tests_a_change_fixed(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text(BROKEN)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "a bad commit")
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return a + b\n")  # the fix, uncommitted
    out = run_cli(root, "verify", "--run", "--show-fixed", "--test-command", CMD).stdout
    assert "PASSED" in out, out
    assert "fixed by this change (fail alone at the base, pass alone now):" in out, out
    assert "tests/test_m0.py::" in out and "tests/test_m1.py::" in out, out
    plain = run_cli(root, "verify", "--run", "--rerun", "--test-command", CMD).stdout
    assert "fixed by this change" not in plain, plain  # never claimed without --show-fixed


@needs_sandbox
def test_show_fixed_never_claims_a_fix_the_base_did_not_show(tmp_path: Path):
    root = _project(tmp_path)
    (root / "calc" / "core.py").write_text("def add(a, b):\n    return b + a\n")  # a harmless edit
    out = run_cli(root, "verify", "--run", "--show-fixed", "--test-command", CMD).stdout
    assert "fixed by this change: none (no selected test fails alone at the base and passes alone now)" in out, out


def _m9(root: Path, body: str) -> None:
    (root / "tests" / "test_m9.py").write_text("import unittest\nfrom calc.core import add\n\n\nclass T(unittest.TestCase):\n"
                                              + body)


BAD = "    def test_bad(self):\n        self.assertEqual(add(2, 2), 5)\n"
OK = "    def test_ok(self):\n        self.assertEqual(add(1, 1), 2)\n"


@needs_sandbox
def test_show_fixed_does_not_call_a_deleted_test_fixed(tmp_path: Path):
    """Review of #26: the change deletes the failing test; nothing was fixed."""
    root = _project(tmp_path, {"tests/test_m9.py": ""})
    _m9(root, BAD + OK)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "a failing test")
    _m9(root, OK)
    out = run_cli(root, "verify", "--run", "--show-fixed", "--test-command", CMD).stdout
    assert "test_bad" not in out.split("fixed by this change")[-1], out


@needs_sandbox
def test_show_fixed_does_not_call_a_skipped_test_fixed(tmp_path: Path):
    root = _project(tmp_path, {"tests/test_m9.py": ""})
    _m9(root, BAD + OK)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "a failing test")
    _m9(root, "    @unittest.skip('later')\n" + BAD + OK)
    out = run_cli(root, "verify", "--run", "--show-fixed", "--test-command", CMD).stdout
    assert "test_bad" not in out.split("fixed by this change")[-1], out


@needs_sandbox
def test_show_fixed_does_not_call_an_order_dependent_test_fixed(tmp_path: Path):
    """It fails at the base only after another test pollutes shared state; alone it passes at the base too."""
    root = _project(tmp_path, {"calc/state.py": "VALUE = [0]\n", "calc/other.py": "X = 1\n",
                               "tests/test_a_pollute.py": "import unittest\nfrom calc import state\n\n\n"
                               "class P(unittest.TestCase):\n    def test_a_pollute(self):\n        state.VALUE[0] = 1\n",
                               "tests/test_victim.py": "import unittest\nfrom calc import state, other\n\n\n"
                               "class V(unittest.TestCase):\n    def test_victim(self):\n"
                               "        self.assertEqual(state.VALUE[0] + other.X, 1)\n"})
    (root / "calc" / "other.py").write_text("X = 1  # a harmless edit\n")
    out = run_cli(root, "verify", "--run", "--show-fixed", "--test-command", CMD).stdout
    assert "test_victim" not in out.split("fixed by this change")[-1], out


def test_pre_existing_failures_that_look_like_the_missing_network_are_named():
    """speed-v1: pyjwt's JWKS client tests fail inside the sandbox (no network) at the base and the change alike;
    the project's own run passes. The report now says the failures look like the sandbox's denied network."""
    from repo_ai.verify import report
    def row(test, tail):
        return {"test": test, "status": "fail", "baseline": "fail", "confirmed": True, "output_tail": tail}
    rec = {"verdict": "failing (all failures pre-existing at the base)", "results": [
        row("tests/test_jwks_client.py",
            "E   urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>"),
        row("tests/test_other.py", "E   AssertionError: 1 != 2")]}
    s = report.summarize(rec)
    assert s["pre_existing"] == ["tests/test_jwks_client.py", "tests/test_other.py"]
    assert s["sandbox_network_suspected"] == ["tests/test_jwks_client.py"]
    text = "\n".join(report._outcome(rec, s, []))
    assert "sandbox's denied network" in text and "test_jwks_client.py" in text.split("denied network")[1]
    # a NEW failure is never explained away, whatever it prints
    new = {"test": "tests/test_new.py", "status": "fail", "baseline": "pass", "confirmed": True,
           "output_tail": "E   socket.gaierror: [Errno -3] Temporary failure in name resolution"}
    s2 = report.summarize({"verdict": "regression", "results": [new]})
    assert s2["sandbox_network_suspected"] == [] and s2["new_failures"]
