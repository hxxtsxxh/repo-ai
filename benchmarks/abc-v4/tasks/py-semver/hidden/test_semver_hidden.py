import pytest
from semver import compare_versions


def test_numeric_prerelease_identifiers_compare_as_integers():
    assert compare_versions("1.0.0-alpha.2", "1.0.0-alpha.10") == -1


def test_numeric_identifier_is_lower_than_alphanumeric():
    assert compare_versions("1.0.0-1", "1.0.0-alpha") == -1
    assert compare_versions("1.0.0-alpha.1", "1.0.0-alpha.beta") == -1


def test_fewer_identifiers_is_lower_when_prefix_is_equal():
    assert compare_versions("1.0.0-alpha", "1.0.0-alpha.1") == -1
    assert compare_versions("1.0.0-alpha.1", "1.0.0-alpha") == 1


def test_build_metadata_is_ignored():
    assert compare_versions("1.0.0+build.5", "1.0.0+other") == 0
    assert compare_versions("1.0.0-rc.1+a", "1.0.0-rc.1") == 0


def test_numeric_compare_is_not_lexicographic():
    assert compare_versions("1.10.0", "1.9.0") == 1


def test_leading_zeros_and_empty_identifiers_are_rejected():
    for bad in ("01.0.0", "1.0.0-01", "1.0.0-", "1.0.0-a..b", "1.0.0+", "1.0.0-a+", "v1.0.0", "1.0.0\n", "1.0.0-\u00e9", "1.\u0663.0"):
        with pytest.raises(ValueError):
            compare_versions(bad, "1.0.0")
    assert compare_versions("1.0.0-0", "1.0.0-0") == 0
    assert compare_versions("1.0.0+001", "1.0.0") == 0


def test_second_argument_is_validated_too():
    with pytest.raises(ValueError):
        compare_versions("1.0.0", "1.0")
