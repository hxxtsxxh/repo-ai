"""A test runner missing from the environment verify used is "not verified", never "no new failures" (found by the
0.11.8 smoke install: pytest absent from the interpreter, every test failing the same way at base and change)."""
from __future__ import annotations

import pytest

from repo_ai.verify import evidence

MISSING = "/x/bin/python: No module named pytest\nModuleNotFoundError: No module named 'pytest'"


def _row(test: str, tail: str, baseline: str = "fail") -> dict:
    return {"test": test, "status": "fail", "baseline": baseline, "output_tail": tail}


@pytest.mark.parametrize("tail,name", [
    (MISSING, "pytest"),
    ("sh: 1: vitest: not found", "vitest"),
    ("Error: Cannot find module 'jest'", "jest"),
    ("ModuleNotFoundError: No module named 'pytest_asyncio'", "pytest_asyncio"),
])
def test_runner_missing_is_recognised(tail, name):
    assert evidence.runner_missing(tail) == name


def test_ordinary_failures_are_not_a_missing_runner():
    assert evidence.runner_missing("ModuleNotFoundError: No module named 'humanize._version'") is None
    assert evidence.runner_missing("AssertionError: assert 3 == 2") is None


def test_every_failure_a_missing_runner_is_not_verified():
    rows = [_row("tests/test_a.py", MISSING), _row("tests/test_b.py", MISSING, baseline="absent")]
    v = evidence.verdict(rows, None, 2, False)
    assert v.startswith("not verified: the test runner could not start") and "pytest" in v
    assert not evidence.is_passing(v)


def test_a_real_failure_next_to_a_missing_runner_keeps_the_usual_verdict():
    rows = [_row("tests/test_a.py", MISSING), _row("tests/test_b.py", "AssertionError: assert 3 == 2", "pass")]
    assert evidence.verdict(rows, None, 2, False) == "regression"


def test_a_full_suite_that_could_not_start_counts_too():
    full = {"status": "fail", "attributed": False, "output_tail": MISSING}
    assert evidence.verdict([], full, 0, True).startswith("not verified: the test runner could not start")


@pytest.mark.parametrize("tail", [
    "ModuleNotFoundError: No module named 'pytest_foo'",  # the project's own plugin package, broken by the change
    "ModuleNotFoundError: No module named 'pytest_utils'",  # a deleted test helper
    MISSING,
])
def test_a_file_that_passed_at_the_base_is_a_regression_whatever_its_message(tail):
    """Review of #89: the runner demonstrably started at the base in this environment."""
    assert evidence.verdict([_row("tests/test_a.py", tail, baseline="pass")], None, 1, False) == "regression"


@pytest.mark.parametrize("tail", [
    "ModuleNotFoundError: No module named '_pytest.compat'",
    "ModuleNotFoundError: No module named 'pytest.foo'",
    "AssertionError: expected 'sh: jest: not found' to equal ''",
    "E   assert 'Error: Cannot find module \\'jest\\'' == ''",
])
def test_submodules_and_quoted_text_are_not_a_missing_runner(tail):
    assert evidence.runner_missing(tail) is None


def test_the_report_lists_every_file_as_could_not_run():
    from repo_ai.verify import report
    rec = {"verdict": evidence.verdict([_row("tests/test_a.py", MISSING), _row("tests/test_new.py", MISSING, "absent")],
                                       None, 2, False),
           "results": [{**_row("tests/test_a.py", MISSING), "failing_tests": [], "failures": {}},
                       {**_row("tests/test_new.py", MISSING, "absent"), "failing_tests": [], "failures": {},
                        "new_failing_tests": []}]}
    lines = report._outcome(rec, report.summarize(rec), [])
    text = "\n".join(lines)
    assert lines[0].startswith("NOT VERIFIED: the test runner could not start")
    assert "could not run (no test runner): tests/test_a.py, tests/test_new.py" in text
    assert "NEW" not in text and "already failing at the base" not in text


def test_a_file_that_passed_in_the_same_run_means_the_runner_started():
    """Review round 2 of #89: a new file importing a missing local helper, next to a passing file."""
    rows = [_row("tests/test_new.py", "ModuleNotFoundError: No module named 'pytest_helpers'", baseline="absent"),
            {"test": "tests/test_ok.py", "status": "pass", "baseline": "pass", "output_tail": ""}]
    assert evidence.verdict(rows, None, 2, False) == "regression"
