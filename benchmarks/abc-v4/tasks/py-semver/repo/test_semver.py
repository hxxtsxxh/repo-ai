import pytest
from semver import compare_versions


def test_numeric_order():
    assert compare_versions("1.2.3", "1.2.4") == -1
    assert compare_versions("2.0.0", "1.9.9") == 1


def test_equal():
    assert compare_versions("1.0.0", "1.0.0") == 0


def test_release_is_higher_than_its_prerelease():
    assert compare_versions("1.0.0-alpha", "1.0.0") == -1


def test_alpha_before_beta():
    assert compare_versions("1.0.0-alpha", "1.0.0-beta") == -1


def test_rejects_garbage():
    with pytest.raises(ValueError):
        compare_versions("1.0", "1.0.0")
    with pytest.raises(ValueError):
        compare_versions(1, "1.0.0")
