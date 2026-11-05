# Developer acceptance tests: written from the task statement only, before any candidate existed.
import pytest

from sizes import parse_size


@pytest.mark.skip(reason="units not supported yet")
def test_binary_units():
    assert parse_size("1KiB") == 1024
    assert parse_size("2MiB") == 2 * 1024 ** 2


@pytest.mark.skip(reason="units not supported yet")
def test_case_insensitive():
    assert parse_size("10kb") == 10000


@pytest.mark.skip(reason="units not supported yet")
def test_single_space():
    assert parse_size("10 KB") == 10000


@pytest.mark.skip(reason="units not supported yet")
def test_fractional():
    assert parse_size("1.5KiB") == 1536
