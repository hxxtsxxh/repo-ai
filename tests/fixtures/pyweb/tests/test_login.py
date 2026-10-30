import pytest

from app.auth.login import LoginError, validate_credentials


def test_rejects_bad_email():
    with pytest.raises(LoginError):
        validate_credentials("nope", "pw")
