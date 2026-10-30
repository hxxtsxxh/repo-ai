# Hidden oracle (never in a candidate workspace). Test names carry the requirement id.
import pytest

from backoff import delays


def test_r1_cap_reached():
    assert delays(5, 1, 2, 5) == [1, 2, 4, 5, 5]


def test_r1_cap_equal_to_base():
    assert delays(3, 2, 1, 2) == [2, 2, 2]


def test_r1_cap_from_start():
    assert delays(3, 4, 2, 4) == [4, 4, 4]


def test_r2_zero_attempts():
    assert delays(0) == []


def test_r2_negative_attempts():
    for bad in (-1, -10):
        with pytest.raises(ValueError):
            delays(bad)


def test_r3_base_not_positive():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            delays(3, bad, 2, 10)


def test_r3_factor_below_one():
    with pytest.raises(ValueError):
        delays(3, 1, 0.5, 10)


def test_r3_cap_below_base():
    with pytest.raises(ValueError):
        delays(2, 5, 2, 4)


def test_r4_uncapped_unchanged():
    assert delays(3, 1, 2, 100) == [1, 2, 4]
    assert delays(4, 0.5, 2, 100) == [0.5, 1, 2, 4]


def test_r5_bool_rejected():
    for bad in (True, False):
        with pytest.raises(TypeError):
            delays(bad)


def test_r5_non_int_rejected():
    for bad in (2.0, "3", None):
        with pytest.raises(TypeError):
            delays(bad)


def test_r5_type_check_first():
    with pytest.raises(TypeError):
        delays(-1.5)
    with pytest.raises(TypeError):
        delays(True, 0)
