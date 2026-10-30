# Developer acceptance tests: written from the task statement only, before any candidate existed.
import pytest

from sizes import parse_size


def test_binary_units():
    with pytest.raises(ValueError):
        parse_size("1KiB")


def test_case_insensitive():
    with pytest.raises(ValueError):
        parse_size("10kb")


def test_single_space():
    with pytest.raises(ValueError):
        parse_size("10 KB")


def test_fractional():
    with pytest.raises(ValueError):
        parse_size("1.5KiB")
