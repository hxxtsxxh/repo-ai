# Developer acceptance tests: written from the task statement only, before any candidate existed.
from sizes import parse_size


def test_binary_units():
    assert parse_size("1KiB") == 1024
    assert parse_size("2MiB") == 2 * 1024 ** 2


def test_case_insensitive():
    assert parse_size("10kb") == 10000


def test_single_space():
    assert parse_size("10 KB") == 10000


def test_fractional():
    assert parse_size("1.5KiB") == 1536
