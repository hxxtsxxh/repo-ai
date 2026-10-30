# Follow-up pool: one test per requirement, written from the statement only, before any candidate existed.
# Used only by the exploratory B+ / A+ arms (PREREGISTRATION.md section 5.4); never part of the hidden oracle.
import pytest

from sizes import parse_size


def test_followup_r1():
    assert parse_size("3GiB") == 3 * 1024 ** 3


def test_followup_r2():
    assert parse_size("1gib") == 1024 ** 3


def test_followup_r3():
    with pytest.raises(ValueError):
        parse_size(" 10KB")


def test_followup_r4():
    with pytest.raises(ValueError):
        parse_size("1.3B")


def test_followup_r5():
    with pytest.raises(ValueError):
        parse_size("1XB")
