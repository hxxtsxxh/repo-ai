# Hidden oracle (never in a candidate workspace). Test names carry the requirement id.
import pytest

from sizes import parse_size


def test_r1_binary_units():
    assert parse_size("1KiB") == 1024
    assert parse_size("2MiB") == 2 * 1024 ** 2
    assert parse_size("3GiB") == 3 * 1024 ** 3


def test_r2_case_insensitive():
    assert parse_size("10kb") == 10000
    assert parse_size("1gib") == 1024 ** 3
    assert parse_size("5b") == 5
    assert parse_size("2Mb") == 2 * 1000 ** 2


def test_r3_single_space():
    assert parse_size("10 KB") == 10000
    assert parse_size("1 KiB") == 1024


def test_r3_other_whitespace_rejected():
    for bad in (" 10KB", "10KB ", "10  KB", "10\tKB", "10 "):
        with pytest.raises(ValueError):
            parse_size(bad)


def test_r4_fractions():
    assert parse_size("1.5KiB") == 1536
    assert parse_size("0.5KB") == 500
    assert parse_size("2.25KiB") == 2304


def test_r4_not_whole_rejected():
    for bad in ("1.3B", "0.1KiB"):
        with pytest.raises(ValueError):
            parse_size(bad)


def test_r4_exact_arithmetic():
    assert parse_size("1.1KB") == 1100
    assert parse_size("4.35MB") == 4350000


def test_r5_existing_forms():
    assert parse_size("7") == 7
    assert parse_size("10KB") == 10000
    assert parse_size("2GB") == 2 * 10 ** 9


def test_r5_existing_errors():
    for bad in ("", "KB", "-1", "1XB"):
        with pytest.raises(ValueError):
            parse_size(bad)
    for bad in (10, None, b"10"):
        with pytest.raises(TypeError):
            parse_size(bad)
