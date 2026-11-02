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
