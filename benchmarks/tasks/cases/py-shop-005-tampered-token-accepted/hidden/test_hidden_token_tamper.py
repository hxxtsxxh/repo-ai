import unittest

from shop.app import create_app
from shop.errors import AuthError
from shop.services.auth import issue_token, verify_token

T0 = 1_700_000_000


def _flip_last(token):
    body, sig = token.split(".")
    last = "0" if sig[-1] != "0" else "1"
    return f"{body}.{sig[:-1]}{last}"


class TokenTamperTest(unittest.TestCase):
    def test_modified_signature_rejected(self):
        token = issue_token("usr_1", now=T0)
        with self.assertRaises(AuthError):
            verify_token(_flip_last(token), now=T0 + 1)

    def test_truncated_or_extended_signature_rejected(self):
        token = issue_token("usr_1", now=T0)
        body, sig = token.split(".")
        for bad in (f"{body}.{sig[:20]}", f"{body}.{sig}00"):
            with self.assertRaises(AuthError):
                verify_token(bad, now=T0 + 1)

    def test_api_rejects_tampered_token(self):
        app = create_app()
        headers = app.register_and_login("sec@example.com")
        good = headers["Authorization"].split(" ", 1)[1]
        self.assertEqual(app.request("GET", "/users/me", headers=headers)["status"], 200)
        resp = app.request("GET", "/users/me", headers={"Authorization": "Bearer " + _flip_last(good)})
        self.assertEqual(resp["status"], 401)

    def test_regression_valid_token(self):
        token = issue_token("usr_9", ["customer"], now=T0)
        self.assertEqual(verify_token(token, now=T0 + 10)["sub"], "usr_9")


if __name__ == "__main__":
    unittest.main()
