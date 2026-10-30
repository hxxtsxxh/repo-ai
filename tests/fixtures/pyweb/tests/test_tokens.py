from app.auth.tokens import issue_token, verify_token


def test_roundtrip():
    assert verify_token(issue_token(7))["sub"] == 7
