import pytest
from duration import parse_duration


def test_combined_and_zero():
    assert parse_duration("1d2h3m4s") == 93784
    assert parse_duration("1h30m") == 5400
    assert parse_duration("0s") == 0


def test_outer_whitespace_ignored():
    assert parse_duration("  5m \n") == 300


@pytest.mark.parametrize("bad", ["30m1h", "1h1h", "5", "5x", "1.5h", "-5s", "+5s", "1h 30m", "abc", "1h30", "   ", "h", "1H", "1h!"])
def test_invalid_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
