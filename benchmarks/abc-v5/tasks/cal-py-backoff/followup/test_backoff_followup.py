# Follow-up pool: one test per requirement, written from the statement only, before any candidate existed.
# Used only by the exploratory B+ / A+ arms (PREREGISTRATION.md section 5.4); never part of the hidden oracle.
import pytest

from backoff import delays


def test_followup_r1():
    assert delays(4, 2, 3, 10) == [2, 6, 10, 10]


def test_followup_r2():
    with pytest.raises(ValueError):
        delays(-3)


def test_followup_r3():
    with pytest.raises(ValueError):
        delays(3, 1, 0.5, 10)


def test_followup_r4():
    assert delays(4, 0.5, 2, 100) == [0.5, 1, 2, 4]


def test_followup_r5():
    with pytest.raises(TypeError):
        delays(True)
