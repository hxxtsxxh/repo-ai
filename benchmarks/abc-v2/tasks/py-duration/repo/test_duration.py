import pytest
from duration import parse_duration


def test_single_units():
    assert parse_duration("90s") == 90
    assert parse_duration("1h") == 3600


def test_empty_rejected():
    with pytest.raises(ValueError):
        parse_duration("")
