# Shipped tests of the synthetic sizes module (the "upstream" suite).
import pytest

from sizes import parse_size


def test_plain_bytes():
    assert parse_size("7") == 7


def test_decimal_units():
    assert parse_size("10KB") == 10000
    assert parse_size("2GB") == 2 * 10 ** 9


def test_invalid_strings():
    for bad in ("", "KB", "-1", "1XB"):
        with pytest.raises(ValueError):
            parse_size(bad)


def test_non_str():
    with pytest.raises(TypeError):
        parse_size(10)
